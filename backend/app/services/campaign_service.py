import csv
import io
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.repositories.campaign import CampaignRepository
from app.repositories.product import ProductRepository
from app.schemas.campaign import CampaignRowSchema, CampaignUploadResponse

REQUIRED_COLUMNS = {
    "platform",
    "campaign_name",
    "date",
    "impressions",
    "clicks",
    "conversions",
    "spend",
    "revenue",
}
MAX_CSV_BYTES = 5 * 1024 * 1024


class CampaignService:
    def __init__(self, session: Session) -> None:
        self.product_repository = ProductRepository(session)
        self.campaign_repository = CampaignRepository(session)

    def import_csv(
        self, product_id: int, file_name: str, content: bytes
    ) -> CampaignUploadResponse:
        if self.product_repository.get(product_id) is None:
            raise AppError("Product not found", status_code=404)

        rows = self._parse_and_validate(file_name, content)
        campaigns = self.campaign_repository.create_many(product_id, rows)
        return CampaignUploadResponse(
            product_id=product_id, imported_count=len(campaigns)
        )

    @staticmethod
    def _parse_and_validate(
        file_name: str, content: bytes
    ) -> list[CampaignRowSchema]:
        if Path(file_name).suffix.casefold() != ".csv":
            raise AppError("Only CSV files are supported", status_code=422)
        if not content:
            raise AppError("CSV file is empty", status_code=422)
        if len(content) > MAX_CSV_BYTES:
            raise AppError("CSV file exceeds the 5 MB limit", status_code=422)

        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise AppError("CSV file must use UTF-8 encoding", status_code=422) from exc

        reader = csv.DictReader(io.StringIO(text, newline=""))
        if reader.fieldnames is None:
            raise AppError("CSV header is missing", status_code=422)
        headers = [header.strip() for header in reader.fieldnames]
        if len(headers) != len(set(headers)):
            raise AppError("CSV contains duplicate column names", status_code=422)
        missing_columns = sorted(REQUIRED_COLUMNS - set(headers))
        if missing_columns:
            raise AppError(
                f"CSV is missing required columns: {', '.join(missing_columns)}",
                status_code=422,
            )

        validated_rows: list[CampaignRowSchema] = []
        for row_number, row in enumerate(reader, start=2):
            normalized_row = {
                str(key).strip(): value for key, value in row.items() if key is not None
            }
            if not any(str(value or "").strip() for value in normalized_row.values()):
                continue
            try:
                validated_rows.append(CampaignRowSchema.model_validate(normalized_row))
            except ValidationError as exc:
                error = exc.errors(include_input=False)[0]
                field = ".".join(str(part) for part in error["loc"]) or "row"
                raise AppError(
                    f"Invalid CSV row {row_number}: {field} - {error['msg']}",
                    status_code=422,
                ) from exc

        if not validated_rows:
            raise AppError("CSV contains no campaign rows", status_code=422)
        return validated_rows
