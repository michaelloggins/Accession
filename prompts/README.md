# Extraction Prompts

This directory contains the prompts used for AI document extraction.

## Files

- **system_prompt.txt**: Defines the AI's role, expertise, and behavior
- **user_prompt.txt**: Instructions for extracting data from documents
- **output_format.txt**: JSON schema for the expected output format

## How It Works

When a document is uploaded:

1. **System Prompt** sets the AI's context (medical document analyst)
2. **User Prompt** provides extraction instructions
3. **Output Format** shows the expected JSON structure
4. AI analyzes the document image/PDF
5. Returns structured JSON with extracted data

## Editing Prompts

1. Edit any of the `.txt` files
2. Restart the server: `python -m uvicorn app.main:app --reload`
3. New uploads will use the updated prompts

## Tips

- Keep system_prompt focused on role and expertise
- Keep user_prompt focused on the task and requirements
- Keep output_format as a clear JSON example
- Test changes with sample documents
- Use clear, specific instructions for better extraction accuracy
