"""
Universal Print Service - Microsoft Graph API integration for cloud printing.

This service provides:
- Printer discovery via Universal Print
- ZPL label generation for accession labels
- Print job submission via Graph API

Prerequisites:
1. Microsoft 365 E3/E5 or Universal Print license
2. Universal Print Connector installed on-premises
3. Printers registered with Universal Print
4. Azure AD app registration with Graph API permissions:
   - PrintJob.Create
   - Printer.Read.All
"""

import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class UniversalPrintService:
    """Service for printing via Microsoft Universal Print."""

    GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, access_token: Optional[str] = None):
        """
        Initialize the print service.

        Args:
            access_token: Microsoft Graph API access token (from user's session)
        """
        self.access_token = access_token

    @property
    def is_enabled(self) -> bool:
        """Check if Universal Print is enabled in config."""
        return settings.UNIVERSAL_PRINT_ENABLED

    @property
    def is_configured(self) -> bool:
        """Check if Universal Print is properly configured."""
        return (
            self.is_enabled and
            bool(settings.AZURE_AD_CLIENT_ID) and
            bool(settings.AZURE_AD_CLIENT_SECRET)
        )

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers for Graph API."""
        if not self.access_token:
            raise ValueError("No access token provided for Graph API")
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    async def list_printers(self) -> List[Dict[str, Any]]:
        """
        List all printers available to the current user.

        Returns:
            List of printer objects with id, displayName, location, etc.
        """
        if not self.is_configured:
            logger.warning("Universal Print not configured")
            return []

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.GRAPH_API_BASE}/print/printers",
                    headers=self._get_headers()
                )

                if response.status_code == 200:
                    data = response.json()
                    printers = data.get("value", [])
                    return [
                        {
                            "id": p.get("id"),
                            "name": p.get("displayName"),
                            "location": p.get("location", {}).get("city", ""),
                            "manufacturer": p.get("manufacturer", ""),
                            "model": p.get("model", ""),
                            "is_shared": p.get("isShared", False),
                            "capabilities": p.get("capabilities", {})
                        }
                        for p in printers
                    ]
                else:
                    logger.error(f"Failed to list printers: {response.status_code} - {response.text}")
                    return []

        except Exception as e:
            logger.error(f"Error listing printers: {e}")
            return []

    async def get_printer(self, printer_id: str) -> Optional[Dict[str, Any]]:
        """Get details for a specific printer."""
        if not self.is_configured:
            return None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.GRAPH_API_BASE}/print/printers/{printer_id}",
                    headers=self._get_headers()
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Failed to get printer: {response.status_code}")
                    return None

        except Exception as e:
            logger.error(f"Error getting printer: {e}")
            return None

    async def create_print_job(
        self,
        printer_id: str,
        document_content: bytes,
        content_type: str = "application/octet-stream",
        job_name: str = "Accession Label"
    ) -> Optional[Dict[str, Any]]:
        """
        Create a print job and upload document content.

        For ZPL labels, use content_type="application/octet-stream" and
        pass the raw ZPL commands as document_content.

        Args:
            printer_id: Universal Print printer ID
            document_content: Raw content to print (ZPL commands for labels)
            content_type: MIME type (application/octet-stream for raw/ZPL)
            job_name: Display name for the print job

        Returns:
            Print job details including job ID and status
        """
        if not self.is_configured:
            return {"error": "Universal Print not configured"}

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Step 1: Create the print job
                job_payload = {
                    "configuration": {
                        "contentType": content_type,
                        "copies": 1,
                        "orientation": "portrait"
                    },
                    "displayName": job_name
                }

                response = await client.post(
                    f"{self.GRAPH_API_BASE}/print/printers/{printer_id}/jobs",
                    headers=self._get_headers(),
                    json=job_payload
                )

                if response.status_code not in [200, 201]:
                    return {"error": f"Failed to create job: {response.text}"}

                job = response.json()
                job_id = job.get("id")
                document_id = job.get("documents", [{}])[0].get("id")

                if not document_id:
                    return {"error": "No document ID in job response"}

                # Step 2: Upload the document content
                upload_headers = self._get_headers()
                upload_headers["Content-Type"] = content_type

                upload_response = await client.put(
                    f"{self.GRAPH_API_BASE}/print/printers/{printer_id}/jobs/{job_id}/documents/{document_id}/$value",
                    headers=upload_headers,
                    content=document_content
                )

                if upload_response.status_code not in [200, 201, 204]:
                    return {"error": f"Failed to upload document: {upload_response.text}"}

                # Step 3: Start the print job
                start_response = await client.post(
                    f"{self.GRAPH_API_BASE}/print/printers/{printer_id}/jobs/{job_id}/start",
                    headers=self._get_headers()
                )

                if start_response.status_code in [200, 202]:
                    return {
                        "success": True,
                        "job_id": job_id,
                        "printer_id": printer_id,
                        "status": "submitted"
                    }
                else:
                    return {"error": f"Failed to start job: {start_response.text}"}

        except Exception as e:
            logger.error(f"Print job error: {e}")
            return {"error": str(e)}

    async def get_job_status(self, printer_id: str, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of a print job."""
        if not self.is_configured:
            return None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.GRAPH_API_BASE}/print/printers/{printer_id}/jobs/{job_id}",
                    headers=self._get_headers()
                )

                if response.status_code == 200:
                    job = response.json()
                    return {
                        "job_id": job.get("id"),
                        "status": job.get("status", {}).get("state"),
                        "description": job.get("status", {}).get("description"),
                        "created": job.get("createdDateTime")
                    }

        except Exception as e:
            logger.error(f"Error getting job status: {e}")

        return None


class ZPLLabelGenerator:
    """Generate ZPL II label commands for various label types."""

    @staticmethod
    def accession_label(
        accession_number: str,
        patient_name: str = "",
        date_of_birth: str = "",
        collection_date: str = "",
        label_width_dots: int = 406,  # 2" at 203 DPI
        label_height_dots: int = 203  # 1" at 203 DPI
    ) -> str:
        """
        Generate ZPL for an accession number label with barcode.

        Args:
            accession_number: The accession number (e.g., "A00000123")
            patient_name: Optional patient name
            date_of_birth: Optional DOB
            collection_date: Optional collection date
            label_width_dots: Label width in dots (203 DPI)
            label_height_dots: Label height in dots (203 DPI)

        Returns:
            ZPL II command string
        """
        # Build ZPL commands
        zpl = [
            "^XA",  # Start format
            f"^PW{label_width_dots}",  # Print width
            f"^LL{label_height_dots}",  # Label length
            "^PON",  # Print orientation normal
            "^LH0,0",  # Label home position
        ]

        # Accession number text (top)
        zpl.append(f"^FO20,10^A0N,24,24^FD{accession_number}^FS")

        # Barcode (Code 128)
        zpl.append(f"^FO20,40^BCN,60,N,N,N^FD{accession_number}^FS")

        # Patient name (if provided)
        y_pos = 110
        if patient_name:
            # Truncate to fit label
            name = patient_name[:25]
            zpl.append(f"^FO20,{y_pos}^A0N,18,18^FD{name}^FS")
            y_pos += 22

        # DOB (if provided)
        if date_of_birth:
            zpl.append(f"^FO20,{y_pos}^A0N,16,16^FDDOB: {date_of_birth}^FS")
            y_pos += 20

        # Collection date (if provided)
        if collection_date:
            zpl.append(f"^FO200,{y_pos - 20}^A0N,16,16^FD{collection_date}^FS")

        # End format
        zpl.append("^XZ")

        return "\n".join(zpl)

    @staticmethod
    def specimen_label(
        accession_number: str,
        specimen_type: str,
        tube_number: int = 1,
        total_tubes: int = 1
    ) -> str:
        """
        Generate ZPL for a specimen tube label.

        Args:
            accession_number: The accession number
            specimen_type: Type of specimen (e.g., "SST", "EDTA", "Urine")
            tube_number: This tube's number
            total_tubes: Total number of tubes

        Returns:
            ZPL II command string
        """
        zpl = [
            "^XA",
            "^PW406",  # 2" width
            "^LL152",  # 0.75" height
            "^FO10,8^A0N,20,20^FD{accession_number}^FS",
            f"^FO10,32^BCN,45,N,N,N^FD{accession_number}^FS",
            f"^FO10,85^A0N,22,22^FD{specimen_type}^FS",
            f"^FO280,85^A0N,22,22^FD{tube_number}/{total_tubes}^FS",
            "^XZ"
        ]
        return "\n".join(zpl)

    @staticmethod
    def simple_barcode(
        data: str,
        label_text: str = ""
    ) -> str:
        """
        Generate a simple barcode label.

        Args:
            data: Data to encode in barcode
            label_text: Optional text below barcode

        Returns:
            ZPL II command string
        """
        zpl = [
            "^XA",
            "^PW406",
            "^LL203",
            f"^FO30,20^BCN,80,Y,N,N^FD{data}^FS",
        ]

        if label_text:
            zpl.append(f"^FO30,120^A0N,24,24^FD{label_text}^FS")

        zpl.append("^XZ")
        return "\n".join(zpl)

    @staticmethod
    def test_label(
        printer_name: str,
        label_width_dots: int = 406,
        label_height_dots: int = 203,
        test_id: str = None
    ) -> str:
        """
        Generate a test label to verify printer configuration.

        Includes:
        - Printer name
        - Test barcode
        - Date/time stamp
        - Border to verify alignment

        Args:
            printer_name: Name of the printer being tested
            label_width_dots: Label width in dots
            label_height_dots: Label height in dots
            test_id: Optional test identifier

        Returns:
            ZPL II command string
        """
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        test_code = test_id or datetime.now().strftime("%H%M%S")

        # Truncate printer name to fit
        printer_display = printer_name[:20] if printer_name else "Unknown"

        zpl = [
            "^XA",  # Start format
            f"^PW{label_width_dots}",  # Print width
            f"^LL{label_height_dots}",  # Label length
            "^PON",  # Print orientation normal
            "^LH0,0",  # Label home position

            # Border rectangle to verify print area
            f"^FO5,5^GB{label_width_dots - 10},{label_height_dots - 10},2^FS",

            # Header: TEST PRINT
            "^FO15,15^A0N,28,28^FDTEST PRINT^FS",

            # Checkmark icon (indicates success if visible)
            f"^FO{label_width_dots - 50},15^A0N,28,28^FD[OK]^FS",

            # Printer name
            f"^FO15,50^A0N,20,20^FD{printer_display}^FS",

            # Test barcode
            f"^FO15,75^BCN,50,Y,N,N^FDTEST{test_code}^FS",

            # Timestamp
            f"^FO15,{label_height_dots - 30}^A0N,16,16^FD{timestamp}^FS",

            # Label size info
            f"^FO{label_width_dots - 100},{label_height_dots - 30}^A0N,14,14^FD{label_width_dots}x{label_height_dots}^FS",

            "^XZ"  # End format
        ]

        return "\n".join(zpl)

    @staticmethod
    def alignment_test(
        label_width_dots: int = 406,
        label_height_dots: int = 203
    ) -> str:
        """
        Generate an alignment test pattern.

        Prints corner markers and center crosshairs to verify
        label alignment and print area.

        Args:
            label_width_dots: Label width in dots
            label_height_dots: Label height in dots

        Returns:
            ZPL II command string
        """
        center_x = label_width_dots // 2
        center_y = label_height_dots // 2

        zpl = [
            "^XA",
            f"^PW{label_width_dots}",
            f"^LL{label_height_dots}",
            "^PON",
            "^LH0,0",

            # Outer border
            f"^FO0,0^GB{label_width_dots},{label_height_dots},2^FS",

            # Corner markers (L shapes)
            # Top-left
            "^FO5,5^GB30,2,2^FS",
            "^FO5,5^GB2,30,2^FS",
            # Top-right
            f"^FO{label_width_dots - 35},5^GB30,2,2^FS",
            f"^FO{label_width_dots - 7},5^GB2,30,2^FS",
            # Bottom-left
            f"^FO5,{label_height_dots - 7}^GB30,2,2^FS",
            f"^FO5,{label_height_dots - 35}^GB2,30,2^FS",
            # Bottom-right
            f"^FO{label_width_dots - 35},{label_height_dots - 7}^GB30,2,2^FS",
            f"^FO{label_width_dots - 7},{label_height_dots - 35}^GB2,30,2^FS",

            # Center crosshair
            f"^FO{center_x - 20},{center_y}^GB40,2,2^FS",
            f"^FO{center_x},{center_y - 20}^GB2,40,2^FS",

            # Size text in center
            f"^FO{center_x - 40},{center_y + 25}^A0N,16,16^FD{label_width_dots}x{label_height_dots}^FS",

            "^XZ"
        ]

        return "\n".join(zpl)


# Service instance helpers
def get_print_service(access_token: str = None) -> UniversalPrintService:
    """Get a Universal Print service instance."""
    return UniversalPrintService(access_token=access_token)


def get_label_generator() -> ZPLLabelGenerator:
    """Get a ZPL label generator instance."""
    return ZPLLabelGenerator()
