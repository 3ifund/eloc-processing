"""
NER Verification Service

Uses Hugging Face BERT-based NER to validate extracted fields.
Provides third verification layer alongside Claude and OpenAI.
"""
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Field to NER entity type mapping
FIELD_TO_NER_TYPE = {
    "company_symbol": "ORG",
    "company_name": "ORG",
    "company_signator": "PERSON",
    "signatory_title": None,  # No NER type for titles
    "vwap_purchase_share_amount": "CARDINAL",
    "vwap_purchase_exercise_date": "DATE",
    "vwap_purchase_period_start_date": "DATE",
    "vwap_purchase_period_end_date": "DATE",
    "vwap_purchase_settlement_date": "DATE",
    "aggregate_limit_available": "MONEY",
    "agreement_date": "DATE",
    "sender_name": "PERSON",
    "sender_emails": None,  # No NER type for emails
    "email_subject": None,  # No NER type
    "email_body": None,  # No NER type
}


@dataclass
class NEREntity:
    """A single NER entity"""
    text: str
    entity_type: str
    score: float
    start: int
    end: int


@dataclass
class NERValidationResult:
    """Result of NER validation for a single field"""
    field_name: str
    value: Any
    ner_type: Optional[str]
    found_in_ner: bool
    ner_score: float
    matched_entity: Optional[str] = None


class NERVerificationService:
    """
    Verifies extracted fields using Hugging Face NER.

    Uses tner/roberta-large-ontonotes5 model which supports:
    - PERSON (signatories)
    - ORG (companies)
    - DATE (transaction dates)
    - MONEY (dollar amounts)
    - CARDINAL (numbers like share counts)
    """

    def __init__(self, model_name: str = "tner/roberta-large-ontonotes5", threshold: float = 0.9):
        """
        Initialize NER service.

        Args:
            model_name: Hugging Face model to use
            threshold: Minimum confidence score to consider a match (default 0.9)
        """
        self.model_name = model_name
        self.threshold = threshold
        self._pipeline = None
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization of the NER pipeline"""
        if not self._initialized:
            from transformers import pipeline
            logger.info(f"Loading NER model: {self.model_name}")
            self._pipeline = pipeline(
                "ner",
                model=self.model_name,
                aggregation_strategy="simple"
            )
            self._initialized = True
            logger.info("NER model loaded successfully")

    def extract_entities(self, text: str) -> List[NEREntity]:
        """
        Extract all entities from text.

        Args:
            text: Document text

        Returns:
            List of NEREntity objects
        """
        self._ensure_initialized()

        # Limit text length to avoid memory issues
        max_length = 10000
        if len(text) > max_length:
            text = text[:max_length]

        raw_entities = self._pipeline(text)

        entities = []
        for ent in raw_entities:
            entities.append(NEREntity(
                text=ent["word"].strip(),
                entity_type=ent["entity_group"],
                score=ent["score"],
                start=ent["start"],
                end=ent["end"]
            ))

        return entities

    def extract_entities_by_type(self, text: str) -> Dict[str, List[NEREntity]]:
        """
        Extract entities grouped by type.

        Args:
            text: Document text

        Returns:
            Dict mapping entity type to list of entities
        """
        entities = self.extract_entities(text)

        by_type = {}
        for ent in entities:
            if ent.entity_type not in by_type:
                by_type[ent.entity_type] = []
            by_type[ent.entity_type].append(ent)

        return by_type

    def _normalize_value(self, value: Any) -> str:
        """Normalize a value for comparison"""
        if value is None:
            return ""

        # Convert to string
        text = str(value).strip().lower()

        # Remove common punctuation for comparison
        for char in [",", ".", "$", "%"]:
            text = text.replace(char, "")

        return text

    def _check_value_in_entities(
        self,
        value: Any,
        entities: List[NEREntity],
        expected_type: str
    ) -> tuple[bool, float, Optional[str]]:
        """
        Check if a value is found in NER entities with expected type.

        Args:
            value: The extracted value to check
            entities: List of NER entities
            expected_type: Expected NER entity type (PERSON, ORG, DATE, etc.)

        Returns:
            Tuple of (found, score, matched_entity_text)
        """
        if value is None or value == "":
            return False, 0.0, None

        normalized_value = self._normalize_value(value)
        if not normalized_value:
            return False, 0.0, None

        best_match = None
        best_score = 0.0

        for ent in entities:
            # Must match expected type
            if ent.entity_type != expected_type:
                continue

            # Must meet threshold
            if ent.score < self.threshold:
                continue

            normalized_entity = self._normalize_value(ent.text)

            # Check for match (substring matching for flexibility)
            is_match = (
                normalized_value in normalized_entity or
                normalized_entity in normalized_value or
                self._fuzzy_match(normalized_value, normalized_entity)
            )

            if is_match and ent.score > best_score:
                best_match = ent.text
                best_score = ent.score

        found = best_match is not None
        return found, best_score, best_match

    def _fuzzy_match(self, value1: str, value2: str) -> bool:
        """
        Simple fuzzy matching for common variations.

        Handles cases like:
        - "75000" vs "75,000"
        - "November 17, 2025" vs "November 17 2025"
        - "2025-11-17" vs "November 17, 2025"
        """
        # Remove all non-alphanumeric characters
        clean1 = "".join(c for c in value1 if c.isalnum())
        clean2 = "".join(c for c in value2 if c.isalnum())

        if clean1 == clean2 or clean1 in clean2 or clean2 in clean1:
            return True

        # Try date matching: convert ISO date to components
        if self._dates_match(value1, value2):
            return True

        return False

    def _dates_match(self, value1: str, value2: str) -> bool:
        """
        Check if two date representations match.

        Handles:
        - "2025-11-17" vs "November 17, 2025"
        - "2025-07-08" vs "July 8, 2025"
        """
        from datetime import datetime

        # Month name to number mapping
        month_names = {
            "january": "01", "february": "02", "march": "03", "april": "04",
            "may": "05", "june": "06", "july": "07", "august": "08",
            "september": "09", "october": "10", "november": "11", "december": "12"
        }

        def extract_date_parts(s: str) -> tuple:
            """Extract (year, month, day) from various formats"""
            s = s.lower().strip()

            # Try ISO format: 2025-11-17
            if len(s) == 10 and s[4] == '-' and s[7] == '-':
                try:
                    return (s[0:4], s[5:7], s[8:10].lstrip('0') or '0')
                except:
                    pass

            # Try text format: November 17, 2025
            for month_name, month_num in month_names.items():
                if month_name in s:
                    # Extract day and year
                    import re
                    numbers = re.findall(r'\d+', s)
                    if len(numbers) >= 2:
                        # Assume format "Month DD, YYYY" or "Month DD YYYY"
                        day = numbers[0].lstrip('0') or '0'
                        year = numbers[1] if len(numbers[1]) == 4 else numbers[0]
                        if len(numbers[1]) == 4:
                            return (numbers[1], month_num, day)
                        elif len(numbers[0]) == 4:
                            return (numbers[0], month_num, numbers[1].lstrip('0') or '0')
                    break

            return None

        parts1 = extract_date_parts(value1)
        parts2 = extract_date_parts(value2)

        if parts1 and parts2:
            return parts1 == parts2

        return False

    def validate_field(
        self,
        field_name: str,
        value: Any,
        entities_by_type: Dict[str, List[NEREntity]]
    ) -> NERValidationResult:
        """
        Validate a single extracted field against NER entities.

        Args:
            field_name: Name of the field
            value: Extracted value
            entities_by_type: NER entities grouped by type

        Returns:
            NERValidationResult
        """
        ner_type = FIELD_TO_NER_TYPE.get(field_name)

        # No NER type for this field - can't validate
        if ner_type is None:
            return NERValidationResult(
                field_name=field_name,
                value=value,
                ner_type=None,
                found_in_ner=False,
                ner_score=0.0,
                matched_entity=None
            )

        entities = entities_by_type.get(ner_type, [])
        found, score, matched = self._check_value_in_entities(value, entities, ner_type)

        return NERValidationResult(
            field_name=field_name,
            value=value,
            ner_type=ner_type,
            found_in_ner=found,
            ner_score=score if found else 0.0,
            matched_entity=matched
        )

    def validate_extraction(
        self,
        extracted_fields: Dict[str, Any],
        document_text: str
    ) -> Dict[str, NERValidationResult]:
        """
        Validate all extracted fields against NER.

        Args:
            extracted_fields: Dict of field_name -> value
            document_text: Original document text

        Returns:
            Dict of field_name -> NERValidationResult
        """
        # Extract all entities once
        entities_by_type = self.extract_entities_by_type(document_text)

        # Log what was found
        for ner_type, ents in entities_by_type.items():
            high_conf = [e for e in ents if e.score >= self.threshold]
            if high_conf:
                logger.debug(f"NER found {len(high_conf)} {ner_type} entities (>={self.threshold})")

        # Validate each field
        results = {}
        for field_name, value in extracted_fields.items():
            results[field_name] = self.validate_field(field_name, value, entities_by_type)

        return results

    def calculate_field_confidence(
        self,
        field_name: str,
        claude_value: Any,
        openai_value: Any,
        ner_validation: NERValidationResult
    ) -> float:
        """
        Calculate confidence for a field using the simple formula:

        If LLMs agree: (100 + NER_score) / 2
        If LLMs disagree: (0 + NER_score) / 2

        Where NER_score is 100 if found with >0.9 confidence, else 0.

        Args:
            field_name: Name of the field
            claude_value: Value extracted by Claude
            openai_value: Value extracted by OpenAI
            ner_validation: NER validation result

        Returns:
            Confidence score between 0 and 100
        """
        # Normalize values for comparison
        claude_norm = self._normalize_value(claude_value)
        openai_norm = self._normalize_value(openai_value)

        # Check if LLMs agree
        llm_agree = (claude_norm == openai_norm)
        llm_score = 100 if llm_agree else 0

        # NER score: 100 if found with high confidence, else 0
        ner_score = 100 if ner_validation.found_in_ner else 0

        # Simple formula
        confidence = (llm_score + ner_score) / 2

        return confidence

    def calculate_all_confidences(
        self,
        claude_fields: Dict[str, Any],
        openai_fields: Dict[str, Any],
        document_text: str
    ) -> Dict[str, Dict[str, Any]]:
        """
        Calculate confidence for all fields.

        Args:
            claude_fields: Fields extracted by Claude
            openai_fields: Fields extracted by OpenAI
            document_text: Original document text

        Returns:
            Dict of field_name -> {value, confidence, llm_agree, ner_validated}
        """
        # Merge field names from both
        all_fields = set(claude_fields.keys()) | set(openai_fields.keys())

        # Get merged values (prefer Claude when they agree, use Claude otherwise)
        merged_fields = {}
        for field in all_fields:
            claude_val = claude_fields.get(field)
            openai_val = openai_fields.get(field)
            # Use Claude's value as the "merged" value
            merged_fields[field] = claude_val if claude_val is not None else openai_val

        # Validate all merged fields against NER
        ner_results = self.validate_extraction(merged_fields, document_text)

        # Calculate confidence for each field
        results = {}
        for field_name in all_fields:
            claude_val = claude_fields.get(field_name)
            openai_val = openai_fields.get(field_name)
            ner_result = ner_results.get(field_name)

            # Skip if no NER result
            if ner_result is None:
                ner_result = NERValidationResult(
                    field_name=field_name,
                    value=merged_fields.get(field_name),
                    ner_type=None,
                    found_in_ner=False,
                    ner_score=0.0
                )

            confidence = self.calculate_field_confidence(
                field_name, claude_val, openai_val, ner_result
            )

            claude_norm = self._normalize_value(claude_val)
            openai_norm = self._normalize_value(openai_val)

            results[field_name] = {
                "value": merged_fields.get(field_name),
                "confidence": confidence,
                "llm_agree": claude_norm == openai_norm,
                "ner_validated": ner_result.found_in_ner,
                "ner_type": ner_result.ner_type,
                "ner_matched": ner_result.matched_entity
            }

        return results


# Global instance (initialized lazily)
ner_service: Optional[NERVerificationService] = None


def get_ner_service() -> NERVerificationService:
    """Get or create the global NER service instance"""
    global ner_service
    if ner_service is None:
        ner_service = NERVerificationService()
    return ner_service
