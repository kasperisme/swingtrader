import os
import json
from datetime import datetime
from pathlib import Path
from openai import OpenAI
from src.logging import logger
from .analysis_schema import IBDAnalysis

# Initialize OpenAI client
client = OpenAI()


def analyze_files(file_paths, instructions, model="gpt-5"):
    """
    Analyze files using OpenAI API with file inputs

    Args:
        file_paths (list): List of file paths to analyze
        instructions (str): System instructions/prompt
        model (str): OpenAI model to use (default: gpt-5)

    Returns:
        str: Analysis response from OpenAI
    """
    messages = []

    messages.append({"role": "developer", "content": instructions})
    try:
        # Add file contents as strings with filename headers
        for file_path in file_paths:
            if os.path.exists(file_path):
                try:
                    # Read file content as string
                    with open(file_path, "r", encoding="utf-8") as f:
                        file_content = f.read()

                    # Get filename for header
                    filename = os.path.basename(file_path)

                    # Add file content with filename header
                    file_text = f"=== {filename} ===\n{file_content}"
                    messages.append({"role": "user", "content": file_text})
                    logger.info(f"Added file to analysis: {filename}")

                except Exception as e:
                    logger.warning(f"Could not read file {file_path}: {e}")

            else:
                logger.warning(f"File not found: {file_path}")

        # Make the API call using structured output
        logger.info(f"Making API call to {model}")
        response = client.chat.completions.create(
            model=model, messages=messages, response_format={"type": "json_object"}
        )

        # Get the parsed structured response
        analysis = response.choices[0].message.content
        logger.info("Successfully received structured analysis from OpenAI")

        # Parse the JSON string to dict and return as JSON string for consistency
        analysis_dict = json.loads(analysis)
        return json.dumps(analysis_dict, indent=2, default=str)

    except Exception as e:
        logger.error(f"Error analyzing files: {e}")
        return f"Error occurred during analysis: {str(e)}"


def save_analysis(analysis, output_file="./output/openai_analysis.json"):
    """
    Save the analysis to a file

    Args:
        analysis (str): The analysis JSON string to save
        output_file (str): Path to save the analysis
    """
    try:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        # Try to parse and pretty-print the JSON
        try:
            analysis_json = json.loads(analysis)
            with open(output_file, "w") as f:
                json.dump(analysis_json, f, indent=2, ensure_ascii=False)
            logger.info(f"Analysis saved as formatted JSON to {output_file}")
        except json.JSONDecodeError as e:
            logger.warning(f"Could not parse as JSON: {e}")
            # If not valid JSON, save as text
            with open(output_file, "w") as f:
                f.write(
                    f"OpenAI Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                )
                f.write("=" * 50 + "\n\n")
                f.write(analysis)
            logger.info(f"Analysis saved as text to {output_file}")

    except Exception as e:
        logger.error(f"Error saving analysis: {e}")


def parse_analysis(analysis_json):
    """
    Parse and extract key information from the structured analysis

    Args:
        analysis_json (str): JSON string from OpenAI analysis

    Returns:
        dict: Parsed analysis data with key information
    """
    try:
        data = json.loads(analysis_json)

        # Extract key information
        result = {
            "ticker": data.get("ticker", "Unknown"),
            "primary_pattern": data.get("primary_pattern", {}).get("name", "None"),
            "pattern_confidence": data.get("primary_pattern", {}).get("confidence", 0),
            "trade_proposal": data.get("trade_proposal"),
            "decision_commentary": data.get("decision_commentary", ""),
            "risk_reward_ratio": (
                data.get("trade_proposal", {}).get("risk_reward_ratio", 0)
                if data.get("trade_proposal")
                else 0
            ),
            "proposal_confidence": (
                data.get("trade_proposal", {}).get("proposal_confidence", 0)
                if data.get("trade_proposal")
                else 0
            ),
            "entry_level": (
                data.get("trade_proposal", {})
                .get("entry_strategy", {})
                .get("entry_level", 0)
                if data.get("trade_proposal")
                else 0
            ),
            "stop_loss": (
                data.get("trade_proposal", {}).get("stop_loss", {}).get("level", 0)
                if data.get("trade_proposal")
                else 0
            ),
            "take_profit": (
                data.get("trade_proposal", {})
                .get("take_profit", {})
                .get("initial_target", 0)
                if data.get("trade_proposal")
                else 0
            ),
        }

        return result

    except json.JSONDecodeError as e:
        logger.error(f"Error parsing analysis JSON: {e}")
        return {"error": f"Invalid JSON: {str(e)}"}
    except Exception as e:
        logger.error(f"Error extracting analysis data: {e}")
        return {"error": f"Parsing error: {str(e)}"}
