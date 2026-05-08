# Security-Control-Mapping-Using-Multi-Agent-AI-Systems-NIST-800-53-to-CIS-v8
# Security Control Mapping Using Multi-Agent AI

A multi-agent pipeline that automates the mapping of NIST SP 800-53 Rev 5 security controls to CIS Controls v8 Safeguards. For each NIST control, the pipeline retrieves a short list of likely CIS matches using semantic search, then runs four specialized AI agents that classify and explain each mapping.


## What the Pipeline Does

For each NIST 800-53 control, the pipeline:

1. Embeds the control text using a sentence transformer (`all-MiniLM-L6-v2`)
2. Retrieves the top 10 most similar CIS Safeguards from a local ChromaDB instance
3. Verifies each retrieved CIS ID exists in the catalog (Python lookup, not an LLM tool call)
4. Runs four specialized agents that produce:
   - A structured analysis of the NIST control
   - A `STRONG` / `PARTIAL` / `WEAK` classification of each retrieved candidate
   - A technical analysis of the strong and partial safeguards
   - A final human-readable mapping explanation

Output is saved as PDF, JSON, and Excel files for the 101 base controls evaluated.

## Architecture

The pipeline runs four agents in two CrewAI crews:

**Crew 1**
- NIST Analyzer — reads the NIST control and produces a structured analysis
- Semantic Mapper — classifies each verified CIS candidate as `STRONG`, `PARTIAL`, or `WEAK`

**Crew 2**
- CIS Analyzer — analyzes the safeguards rated `STRONG` or `PARTIAL`
- Mapping Interpreter — writes the final mapping explanation

All four agents share the same underlying language model (Gemma 3 12B), running locally through Ollama. No external API calls are made.

## Requirements

- Python 3.10 or higher
- [Ollama](https://ollama.com) installed and running on `http://127.0.0.1:11434`
- Gemma 3 12B model pulled via `ollama pull gemma3:12b`
- Approximately 8 GB of free disk space for the model and embedding database
- A machine with at least 16 GB of RAM (32 GB recommended for smoother runs)

## Setup

Clone the repository and install dependencies:

```bash
git clone <repo-url>
cd <repo-name>
pip install -r requirements.txt
```

Pull the Gemma 3 12B model:

```bash
ollama pull gemma3:12b
```

Make sure Ollama is running in the background before launching the pipeline.

## Project Files

```
.
├── setup_data.py         # Parses NIST 800-53 OSCAL JSON and CIS Excel into structured JSON
├── agents.py             # Defines the four agents, retrieval, and pipeline function
├── run_batch.py          # Runs the pipeline against the full set of 101 base controls
├── parse_results.py      # Compares pipeline output to the official CIS-NIST mapping
├── data/
│   ├── nist_controls_parsed.json      # Parsed NIST 800-53 catalog
│   └── cis_safeguards_parsed.json     # Parsed CIS Controls v8 catalog
├── chromadb/             # Local vector database (created at first run)
└── full_runs/            # Output directory for completed batch runs
```

## Running the Pipeline

Run the steps in order:

```bash
# Step 1: Parse NIST and CIS data sources
python setup_data.py

# Step 2: Run the full pipeline against all 101 base controls
python run_batch.py

# Step 3: Compare results against the official CIS-NIST ground truth mapping
python parse_results.py
```

A full batch run takes roughly seven hours on a development machine, averaging about 260 seconds per control.

## Output

After a batch run, the `full_runs/` directory contains:

- One PDF per NIST control with the full mapping explanation
- One JSON per control with the raw agent outputs
- An Excel summary of all 101 controls with classifications and reasoning

The `parse_results.py` script then produces:

- A control-level agreement breakdown (full recall / partial / zero)
- A safeguard-level breakdown (`STRONG` / `PARTIAL` / `WEAK` distribution)
- Recall, precision, and F1 metrics computed against the official mapping
- A family-level agreement chart

## Design Notes

Two design choices keep the pipeline auditable:

- **Retrieval is separated from reasoning.** All CIS identifiers come from a verified Python lookup, not from the LLM. The agents can be wrong about a rating but cannot invent a safeguard that does not exist.
- **The LLM runs locally.** No data leaves the machine. This makes the pipeline suitable for organizations with sensitive compliance data.
