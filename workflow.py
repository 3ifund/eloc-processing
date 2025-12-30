"""
LangGraph workflow for ELOC document processing - EXTRACTION ONLY
"""
from typing import TypedDict, Literal, List, Optional, Dict
from langgraph.graph import StateGraph, END
import logging
from pathlib import Path
import os
from datetime import datetime
import uuid

from extractors import ExtractorFactory
from classifiers import TripleClassifier
from repositories.instrument_repository import eloc_repo
from repositories.gridfs_repository import gridfs_repo
from repositories.prompts_repository import prompts_repo
from webhooks.webhook_sender import webhook_sender

logger = logging.getLogger(__name__)


class ELOCProcessingState(TypedDict):
    """State for ELOC extraction workflow"""
    # ELOC ID (replaces workflow_id)
    eloc_id: str
    
    # Input - Email metadata
    email_id: str
    email_subject: str
    email_sender: str
    email_sender_name: str
    email_body: str
    
    # Attachments
    all_attachments: List[Dict]
    pdf_word_attachments: List[Dict]
    
    # Extracted text per attachment
    extracted_texts: Dict[str, str]
    
    # Classification results
    classification_results: List[Dict]
    
    # ELOC determination
    eloc_count: int
    eloc_attachment: Optional[Dict]
    eloc_text: Optional[str]
    
    # Critical fields (extraction only - no validation)
    extracted_fields: Optional[Dict]
    
    # Email analysis
    email_analysis: Optional[Dict]
    
    # Webhook
    webhook_sent: bool
    webhook_delivery: Optional[Dict]
    
    # Routing and error handling
    route_to: str
    error: Optional[str]
    processing_stage: str


class ELOCWorkflow:
    """LangGraph workflow for extracting ELOC data (no validation, no processing)"""

    def __init__(self, anthropic_api_key: str, openai_api_key: str = None, references_dir: str = "references"):
        """
        Initialize ELOC extraction workflow

        Args:
            anthropic_api_key: Anthropic API key (for extraction and classification)
            openai_api_key: OpenAI API key (for classification)
            references_dir: Directory with reference ELOC documents
        """
        self.extractor_factory = ExtractorFactory()
        self.classifier = TripleClassifier(anthropic_api_key, openai_api_key, references_dir)

        from anthropic import Anthropic
        self.claude_client = Anthropic(api_key=anthropic_api_key)

        # Cache for prompts
        self.prompts_cache: Dict[str, Dict] = {}

        # Verification orchestrator (dual LLM + trading calendar) - set by main.py
        self.verification_orchestrator = None

        self.workflow = self._build_workflow()

        logger.info("ELOC extraction workflow initialized (extraction only)")
    
    async def _load_prompt(self, prompt_name: str) -> Optional[Dict]:
        """Load prompt from MongoDB (with caching)"""
        if prompt_name in self.prompts_cache:
            return self.prompts_cache[prompt_name]
        
        prompt = await prompts_repo.get_active_prompt(prompt_name)
        
        if not prompt:
            logger.error(f"Prompt not found: {prompt_name}")
            return None
        
        self.prompts_cache[prompt_name] = prompt
        logger.info(f"Loaded prompt: {prompt_name} v{prompt['version']}")
        return prompt
    
    def _build_workflow(self) -> StateGraph:
        """Build the simplified LangGraph workflow"""
        workflow = StateGraph(ELOCProcessingState)
        
        # Add nodes (extraction only)
        workflow.add_node("check_attachments", self.check_attachments_node)
        workflow.add_node("filter_pdf_word", self.filter_pdf_word_node)
        workflow.add_node("extract_text", self.extract_text_node)
        workflow.add_node("classify_documents", self.classify_documents_node)
        workflow.add_node("validate_eloc_count", self.validate_eloc_count_node)
        workflow.add_node("extract_critical_fields", self.extract_critical_fields_node)
        workflow.add_node("analyze_email_body", self.analyze_email_body_node)
        workflow.add_node("send_webhook", self.send_webhook_node)
        workflow.add_node("handle_error", self.handle_error_node)
        
        # Set entry point
        workflow.set_entry_point("check_attachments")
        
        # Define edges
        workflow.add_conditional_edges(
            "check_attachments",
            self.route_after_check_attachments,
            {"continue": "filter_pdf_word", "error": "handle_error"}
        )
        
        workflow.add_conditional_edges(
            "filter_pdf_word",
            self.route_after_filter,
            {"continue": "extract_text", "error": "handle_error"}
        )
        
        workflow.add_edge("extract_text", "classify_documents")
        workflow.add_edge("classify_documents", "validate_eloc_count")
        
        workflow.add_conditional_edges(
            "validate_eloc_count",
            self.route_after_validate_count,
            {
                "extract_fields": "extract_critical_fields",
                "error": "handle_error"
            }
        )
        
        workflow.add_edge("extract_critical_fields", "analyze_email_body")
        workflow.add_edge("analyze_email_body", "send_webhook")
        workflow.add_edge("send_webhook", END)
        workflow.add_edge("handle_error", END)
        
        return workflow.compile()
    
    # ==================== NODES ====================
    
    async def check_attachments_node(self, state: ELOCProcessingState) -> ELOCProcessingState:
        """Check if email has attachments"""
        logger.info("Node: check_attachments")
        
        try:
            if not state["all_attachments"]:
                state["error"] = "No attachments found in email"
                state["route_to"] = "error"
                state["processing_stage"] = "extraction_failed"
                
                await eloc_repo.update_state(
                    state["eloc_id"],
                    "extraction_failed"
                )
                return state
            
            state["route_to"] = "continue"
            state["processing_stage"] = "checking_attachments"
            
            await eloc_repo.update_state(
                state["eloc_id"],
                "processing"
            )
            
            return state
            
        except Exception as e:
            logger.error(f"Error in check_attachments: {e}")
            state["error"] = str(e)
            state["route_to"] = "error"
            return state
    
    async def filter_pdf_word_node(self, state: ELOCProcessingState) -> ELOCProcessingState:
        """Filter for PDF and Word documents only"""
        logger.info("Node: filter_pdf_word")
        
        try:
            pdf_word_attachments = []
            for att in state["all_attachments"]:
                content_type = att.get("content_type", "").lower()
                if "pdf" in content_type or "word" in content_type or "document" in content_type:
                    pdf_word_attachments.append(att)
            
            if not pdf_word_attachments:
                state["error"] = "No PDF or Word documents found"
                state["route_to"] = "error"
                state["processing_stage"] = "extraction_failed"
                
                await eloc_repo.update_state(
                    state["eloc_id"],
                    "extraction_failed"
                )
                return state
            
            state["pdf_word_attachments"] = pdf_word_attachments
            state["route_to"] = "continue"
            state["processing_stage"] = "filtering_attachments"
            
            logger.info(f"Found {len(pdf_word_attachments)} PDF/Word attachments")
            
            await eloc_repo.update_state(
                state["eloc_id"],
                "processing"
            )
            
            return state
            
        except Exception as e:
            logger.error(f"Error in filter_pdf_word: {e}")
            state["error"] = str(e)
            state["route_to"] = "error"
            return state
    
    async def extract_text_node(self, state: ELOCProcessingState) -> ELOCProcessingState:
        """Extract text from PDF/Word documents"""
        logger.info("Node: extract_text")
        
        try:
            extracted_texts = {}
            
            for attachment in state["pdf_word_attachments"]:
                filename = attachment["filename"]
                gridfs_id = attachment.get("gridfs_id")
                
                if not gridfs_id:
                    logger.warning(f"No gridfs_id for {filename}, skipping")
                    continue
                
                logger.info(f"Extracting text from: {filename}")
                
                # Download from GridFS
                file_bytes = gridfs_repo.get_file(gridfs_id)
                
                if not file_bytes:
                    logger.warning(f"Could not retrieve file from GridFS: {gridfs_id}")
                    continue
                
                # Extract text
                content_type = attachment.get("content_type", "")
                extractor = self.extractor_factory.get_extractor(content_type)
                
                if extractor:
                    text = extractor.extract(file_bytes)
                    extracted_texts[filename] = text
                    logger.info(f"Extracted {len(text)} characters from {filename}")
                else:
                    logger.warning(f"No extractor for {content_type}")
            
            state["extracted_texts"] = extracted_texts
            state["processing_stage"] = "extracting_text"
            
            await eloc_repo.update_state(
                state["eloc_id"],
                "processing"
            )
            
            return state
            
        except Exception as e:
            logger.error(f"Error in extract_text: {e}")
            state["error"] = str(e)
            state["route_to"] = "error"
            return state
    
    async def classify_documents_node(self, state: ELOCProcessingState) -> ELOCProcessingState:
        """Classify each document to determine if ELOC"""
        logger.info("Node: classify_documents")
        
        try:
            classification_results = []
            
            for filename, text in state["extracted_texts"].items():
                logger.info(f"Classifying: {filename}")
                
                # Classify with dual method (similarity + LLM)
                result = await self.classifier.classify_document(text)
                result["filename"] = filename
                
                classification_results.append(result)
                
                logger.info(
                    f"Classification: {filename} -> "
                    f"ELOC={result['is_eloc']} "
                    f"(similarity={result['similarity_score']:.2f}, "
                    f"structural={result['structural_score']:.2f})"
                )
            
            state["classification_results"] = classification_results
            state["processing_stage"] = "classifying_documents"
            
            await eloc_repo.update_state(
                state["eloc_id"],
                "processing"
            )
            
            return state
            
        except Exception as e:
            logger.error(f"Error in classify_documents: {e}")
            state["error"] = str(e)
            state["route_to"] = "error"
            return state
    
    async def validate_eloc_count_node(self, state: ELOCProcessingState) -> ELOCProcessingState:
        """Validate that exactly 1 ELOC was found"""
        logger.info("Node: validate_eloc_count")
        
        try:
            eloc_results = [r for r in state["classification_results"] if r["is_eloc"]]
            eloc_count = len(eloc_results)
            
            state["eloc_count"] = eloc_count
            
            if eloc_count == 0:
                state["error"] = "No ELOC documents found"
                state["route_to"] = "error"
                state["processing_stage"] = "extraction_failed"
                
                # Update state with classification results stored in current_data
                updated_data = {
                    "classification_results": state["classification_results"],
                    "error": "no_eloc_found"
                }
                
                await eloc_repo.update_state(
                    state["eloc_id"],
                    "extraction_failed",
                    updated_data=updated_data
                )
                return state
            
            if eloc_count > 1:
                state["error"] = f"Multiple ELOC documents found ({eloc_count})"
                state["route_to"] = "error"
                state["processing_stage"] = "extraction_failed"
                
                # Update state with classification results
                updated_data = {
                    "classification_results": state["classification_results"],
                    "error": "multiple_elocs_found",
                    "eloc_count": eloc_count
                }
                
                await eloc_repo.update_state(
                    state["eloc_id"],
                    "extraction_failed",
                    updated_data=updated_data
                )
                return state
            
            # Exactly 1 ELOC found
            eloc_result = eloc_results[0]
            filename = eloc_result["filename"]
            
            state["eloc_attachment"] = next(
                att for att in state["pdf_word_attachments"] 
                if att["filename"] == filename
            )
            state["eloc_text"] = state["extracted_texts"][filename]
            state["route_to"] = "extract_fields"
            state["processing_stage"] = "eloc_found"
            
            logger.info(f"Found 1 ELOC: {filename}")
            
            # Update state with classification
            updated_data = {
                "classification": eloc_result,
                "eloc_filename": filename
            }
            
            await eloc_repo.update_state(
                state["eloc_id"],
                "processing",
                updated_data=updated_data
            )
            
            return state
            
        except Exception as e:
            logger.error(f"Error in validate_eloc_count: {e}")
            state["error"] = str(e)
            state["route_to"] = "error"
            return state
    
    async def extract_critical_fields_node(self, state: ELOCProcessingState) -> ELOCProcessingState:
        """Extract critical fields from ELOC using dual LLM verification + trading calendar"""
        logger.info("Node: extract_critical_fields")

        try:
            # Use verification orchestrator if available (dual LLM + trading calendar)
            if self.verification_orchestrator:
                extracted_fields = await self._extract_with_orchestrator(state)
            else:
                # Fallback to single-LLM extraction (legacy)
                extracted_fields = await self._extract_with_claude_only(state)

            state["extracted_fields"] = extracted_fields
            state["processing_stage"] = "fields_extracted"

            logger.info(f"Extracted {len(extracted_fields)} fields")

            # Update state with extracted fields
            await eloc_repo.update_state(
                state["eloc_id"],
                "processing",
                updated_data=extracted_fields
            )

            return state

        except Exception as e:
            logger.error(f"Error in extract_critical_fields: {e}")
            state["error"] = str(e)
            state["route_to"] = "error"
            return state

    async def _extract_with_orchestrator(self, state: ELOCProcessingState) -> Dict:
        """
        Extract fields using dual LLM verification (Claude + OpenAI) with trading calendar.

        Returns merged fields including purchase_notice_market_data_date.
        """
        logger.info("Using dual LLM verification orchestrator")

        # Run dual verification
        result = await self.verification_orchestrator.verify(
            document_text=state["eloc_text"],
            email_subject=state["email_subject"],
            email_body=state["email_body"],
            email_sender=state["email_sender"]
        )

        # Check if verification passed (both LLMs agree)
        if not result.passed:
            disagreements = result.get_disagreements()
            logger.warning(
                f"Dual LLM verification disagreement on {len(disagreements)} field(s): "
                f"{[d.field_name for d in disagreements]}"
            )
            # Still use Claude results, but flag the disagreement
            # In production, this might trigger manual review

        # Get merged fields (includes market_data_date if resolved)
        merged_fields = result.get_merged_fields()

        # Convert to {value, confidence} format for MongoDB
        extracted_fields = {}
        for field_name, field_value in merged_fields.items():
            # Skip internal market data fields that we'll handle separately
            if field_name in ('market_data_date_adjusted', 'market_data_date_adjustment_reason', 'market_data_date_tooltip'):
                continue

            # Rename market_data_date to purchase_notice_market_data_date
            if field_name == 'market_data_date':
                field_name = 'purchase_notice_market_data_date'

            # Set confidence based on agreement
            confidence = 0.95 if result.passed else 0.75

            extracted_fields[field_name] = {
                "value": field_value,
                "confidence": confidence,
                "extracted_at": datetime.utcnow().isoformat(),
                "extraction_method": "dual_llm_verification"
            }

        # Add verification metadata
        extracted_fields["_verification"] = {
            "passed": result.passed,
            "agreement_summary": result.agreement_summary,
            "timestamp": result.timestamp.isoformat()
        }

        return extracted_fields

    async def _extract_with_claude_only(self, state: ELOCProcessingState) -> Dict:
        """Legacy extraction using only Claude (fallback when orchestrator not available)"""
        logger.info("Using single-LLM extraction (Claude only)")

        # Load prompt from MongoDB
        prompt_config = await self._load_prompt("critical_fields_extraction")

        if not prompt_config:
            raise ValueError("Critical fields extraction prompt not found")

        # Build prompt
        prompt_template = prompt_config["template"]
        prompt = prompt_template.replace("{eloc_text}", state["eloc_text"])

        # Call Claude
        model_config = prompt_config["model_config"]
        response = self.claude_client.messages.create(
            model=model_config["model"],
            max_tokens=model_config["max_tokens"],
            temperature=model_config["temperature"],
            messages=[{"role": "user", "content": prompt}]
        )

        # Parse response
        import json
        result_text = response.content[0].text.strip()

        # Remove markdown code blocks if present
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
            result_text = result_text.strip()

        extracted_fields = json.loads(result_text)

        # Add metadata
        for field_name, field_data in extracted_fields.items():
            if isinstance(field_data, dict):
                field_data["extracted_at"] = datetime.utcnow().isoformat()
                field_data["prompt_version"] = prompt_config["version"]
                field_data["extraction_method"] = "single_llm"

        return extracted_fields
    
    async def analyze_email_body_node(self, state: ELOCProcessingState) -> ELOCProcessingState:
        """Analyze email body for sender name, questions, personal comments"""
        logger.info("Node: analyze_email_body")
        
        try:
            email_analysis = {}
            
            # 1. Extract sender name from body
            sender_prompt_config = await self._load_prompt("email_sender_name_extraction")
            if sender_prompt_config:
                sender_prompt = sender_prompt_config["template"].replace(
                    "{email_body}", state["email_body"]
                )
                
                sender_response = self.claude_client.messages.create(
                    model=sender_prompt_config["model_config"]["model"],
                    max_tokens=sender_prompt_config["model_config"]["max_tokens"],
                    temperature=sender_prompt_config["model_config"]["temperature"],
                    messages=[{"role": "user", "content": sender_prompt}]
                )
                
                import json
                sender_text = sender_response.content[0].text.strip()
                if sender_text.startswith("```"):
                    sender_text = sender_text.split("```")[1]
                    if sender_text.startswith("json"):
                        sender_text = sender_text[4:]
                    sender_text = sender_text.strip()
                
                sender_data = json.loads(sender_text)
                sender_data["extracted_at"] = datetime.utcnow().isoformat()
                sender_data["prompt_version"] = sender_prompt_config["version"]
                
                email_analysis["sender_name_in_body"] = sender_data
            
            # 2. Extract questions
            questions_prompt_config = await self._load_prompt("email_questions_extraction")
            if questions_prompt_config:
                questions_prompt = questions_prompt_config["template"].replace(
                    "{email_body}", state["email_body"]
                )
                
                questions_response = self.claude_client.messages.create(
                    model=questions_prompt_config["model_config"]["model"],
                    max_tokens=questions_prompt_config["model_config"]["max_tokens"],
                    temperature=questions_prompt_config["model_config"]["temperature"],
                    messages=[{"role": "user", "content": questions_prompt}]
                )
                
                questions_text = questions_response.content[0].text.strip()
                if questions_text.startswith("```"):
                    questions_text = questions_text.split("```")[1]
                    if questions_text.startswith("json"):
                        questions_text = questions_text[4:]
                    questions_text = questions_text.strip()
                
                questions_data = json.loads(questions_text)
                
                # Add IDs and timestamps
                for i, q in enumerate(questions_data.get("questions", []), 1):
                    q["question_id"] = i
                    q["extracted_at"] = datetime.utcnow().isoformat()
                
                email_analysis["questions"] = questions_data.get("questions", [])
            
            # 3. Extract personal comments
            comments_prompt_config = await self._load_prompt("email_personal_comments_extraction")
            if comments_prompt_config:
                comments_prompt = comments_prompt_config["template"].replace(
                    "{email_body}", state["email_body"]
                )
                
                comments_response = self.claude_client.messages.create(
                    model=comments_prompt_config["model_config"]["model"],
                    max_tokens=comments_prompt_config["model_config"]["max_tokens"],
                    temperature=comments_prompt_config["model_config"]["temperature"],
                    messages=[{"role": "user", "content": comments_prompt}]
                )
                
                comments_text = comments_response.content[0].text.strip()
                if comments_text.startswith("```"):
                    comments_text = comments_text.split("```")[1]
                    if comments_text.startswith("json"):
                        comments_text = comments_text[4:]
                    comments_text = comments_text.strip()
                
                comments_data = json.loads(comments_text)
                
                # Add IDs and timestamps
                for i, c in enumerate(comments_data.get("personal_comments", []), 1):
                    c["comment_id"] = i
                    c["extracted_at"] = datetime.utcnow().isoformat()
                
                email_analysis["personal_comments"] = comments_data.get("personal_comments", [])
            
            email_analysis["analysis_completed"] = True
            email_analysis["analysis_completed_at"] = datetime.utcnow().isoformat()
            
            state["email_analysis"] = email_analysis
            state["processing_stage"] = "email_analyzed"
            
            logger.info(
                f"Email analysis complete: "
                f"{len(email_analysis.get('questions', []))} questions, "
                f"{len(email_analysis.get('personal_comments', []))} comments"
            )
            
            # Update state with email analysis
            updated_data = {
                "email_analysis": email_analysis
            }
            
            await eloc_repo.update_state(
                state["eloc_id"],
                "processing",
                updated_data=updated_data
            )
            
            return state
            
        except Exception as e:
            logger.error(f"Error in analyze_email_body: {e}")
            state["error"] = str(e)
            state["route_to"] = "error"
            return state
    
    async def send_webhook_node(self, state: ELOCProcessingState) -> ELOCProcessingState:
        """Send webhook notification that extraction is complete"""
        logger.info("Node: send_webhook")
        
        try:
            # Get complete ELOC data from MongoDB
            eloc_complete = await eloc_repo.get_complete_view(state["eloc_id"])
            
            if not eloc_complete:
                raise ValueError(f"ELOC not found: {state['eloc_id']}")
            
            # Send webhook
            if webhook_sender:
                delivery_status = await webhook_sender.send_extraction_complete(eloc_complete)
                state["webhook_sent"] = delivery_status["delivered"]
                state["webhook_delivery"] = delivery_status
            else:
                logger.warning("Webhook sender not configured")
                state["webhook_sent"] = False
                state["webhook_delivery"] = {"delivered": False, "error": "Webhook sender not configured"}
            
            # Update state to extraction_complete
            await eloc_repo.update_state(
                state["eloc_id"],
                "extraction_complete"
            )
            
            # Mark as no longer requiring action
            await eloc_repo.set_requires_action(state["eloc_id"], False)
            
            logger.info(f"Extraction complete: {state['eloc_id']}")
            
            return state
            
        except Exception as e:
            logger.error(f"Error in send_webhook: {e}")
            state["error"] = str(e)
            state["route_to"] = "error"
            return state
    
    async def handle_error_node(self, state: ELOCProcessingState) -> ELOCProcessingState:
        """Handle workflow errors"""
        logger.info("Node: handle_error")
        
        try:
            error_message = state.get("error", "Unknown error")
            
            logger.error(f"Workflow failed: {error_message}")
            
            # Send error webhook
            if webhook_sender:
                delivery_status = await webhook_sender.send_extraction_failed(
                    state["eloc_id"],
                    error_message
                )
                state["webhook_sent"] = delivery_status["delivered"]
                state["webhook_delivery"] = delivery_status
            else:
                state["webhook_sent"] = False
                state["webhook_delivery"] = {"delivered": False}
            
            # Update state to extraction_failed
            updated_data = {
                "error": error_message,
                "processing_stage": state.get("processing_stage", "error")
            }
            
            await eloc_repo.update_state(
                state["eloc_id"],
                "extraction_failed",
                updated_data=updated_data
            )
            
            # Mark as requiring action (human review needed)
            await eloc_repo.set_requires_action(state["eloc_id"], True)
            
            return state
            
        except Exception as e:
            logger.error(f"Error in handle_error: {e}")
            return state
    
    # ==================== ROUTING FUNCTIONS ====================
    
    def route_after_check_attachments(self, state: ELOCProcessingState) -> Literal["continue", "error"]:
        """Route after checking attachments"""
        return state["route_to"]
    
    def route_after_filter(self, state: ELOCProcessingState) -> Literal["continue", "error"]:
        """Route after filtering"""
        return state["route_to"]
    
    def route_after_validate_count(self, state: ELOCProcessingState) -> Literal["extract_fields", "error"]:
        """Route after validating ELOC count"""
        return state["route_to"]
    
    # ==================== PUBLIC METHODS ====================
    
    async def process_email(self, email_info: Dict, attachments_info: List[Dict]) -> Dict:
        """
        Process email through extraction workflow
        
        Args:
            email_info: Email metadata (from, to, subject, body, etc.)
            attachments_info: List of attachments with file paths
        
        Returns:
            Final state after workflow execution
        """
        # Generate temporary ELOC ID (will be replaced with proper logic later)
        eloc_id = eloc_repo.generate_unique_id()
        
        # Prepare communication data
        communication = {
            "comm_type": "purchase_notice",  # Assume for now
            "email": email_info,
            "attachments": attachments_info,
            "received_at": datetime.utcnow()
        }
        
        # Create initial ELOC instrument in MongoDB
        initial_data = {
            "email_subject": email_info.get("subject", ""),
            "email_from": email_info.get("from", ""),
            "received_at": email_info.get("received_at", "")
        }
        
        await eloc_repo.create_instrument(
            eloc_id,
            communication,
            "processing",  # Initial state
            initial_data
        )
        
        logger.info(f"Created ELOC instrument: {eloc_id}")
        
        # Prepare initial state for workflow
        initial_state = ELOCProcessingState(
            eloc_id=eloc_id,
            email_id=email_info.get("message_id", ""),
            email_subject=email_info.get("subject", ""),
            email_sender=email_info.get("from", ""),
            email_sender_name=email_info.get("from", ""),
            email_body=email_info.get("body", ""),
            all_attachments=attachments_info,
            pdf_word_attachments=[],
            extracted_texts={},
            classification_results=[],
            eloc_count=0,
            eloc_attachment=None,
            eloc_text=None,
            extracted_fields=None,
            email_analysis=None,
            webhook_sent=False,
            webhook_delivery=None,
            route_to="continue",
            error=None,
            processing_stage="initialized"
        )
        
        # Run workflow
        final_state = await self.workflow.ainvoke(initial_state)
        
        return final_state


# Global instance (initialized in main.py)
eloc_workflow = None