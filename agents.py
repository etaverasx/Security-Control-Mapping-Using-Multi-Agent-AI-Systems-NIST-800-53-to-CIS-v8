# agents.py
# Defines all four agents, tools, and the pipeline function.
# The semantic search happens in Python (not through an agent) to prevent hallucinated IDs.
# Import this from run_pipeline.py.

import json
import os
import time
from sentence_transformers import SentenceTransformer
from crewai import Agent, Task, Crew, LLM, Process
import chromadb

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_PATH, "data")
CHROMADB_PATH = os.path.join(BASE_PATH, "chromadb")
TEST_RUNS_PATH = os.path.join(BASE_PATH, "test_runs")
FULL_RUNS_PATH = os.path.join(BASE_PATH, "full_runs")

# ============================================================
# Load data and models
# ============================================================

# load parsed control data
with open(os.path.join(DATA_PATH, "nist_controls_parsed.json"), "r") as f:
    nist_controls = json.load(f)

with open(os.path.join(DATA_PATH, "cis_safeguards_parsed.json"), "r") as f:
    cis_safeguards = json.load(f)

print(f"Loaded {len(nist_controls)} NIST controls and {len(cis_safeguards)} CIS safeguards")

# load embedding model
embedder = SentenceTransformer("all-MiniLM-L6-v2")

# connect to ChromaDB
chroma_client = chromadb.PersistentClient(path=CHROMADB_PATH)
nist_collection = chroma_client.get_or_create_collection(name="nist_800_53")
cis_collection = chroma_client.get_or_create_collection(name="cis_controls_v8")

print(f"ChromaDB connected: {nist_collection.count()} NIST, {cis_collection.count()} CIS")

# ============================================================
# Configure LLM
# ============================================================

llm = LLM(
    model="ollama/gemma3:12b",
    base_url="http://127.0.0.1:11434"
)

# ============================================================
# Programmatic CIS verification (Python, not an agent tool)
# Same pattern as the semantic search -- keeps agents honest.
# ============================================================

def verify_cis_ids(cis_ids: list[str]) -> dict:
    """
    Look up each CIS ID directly in ChromaDB and return a dict of
    {cis_id: metadata_dict} for every ID that actually exists.
    IDs not found are silently dropped -- agents never see them.
    """
    verified = {}
    for raw_id in cis_ids:
        clean_id = raw_id.strip()
        if not clean_id.upper().startswith("CIS"):
            clean_id = f"CIS {clean_id}"
        try:
            result = cis_collection.get(ids=[clean_id])
            if result and result["ids"]:
                verified[clean_id] = result["metadatas"][0]
        except Exception:
            pass
    return verified

# ============================================================
# Define all four agents
# ============================================================

# agent 1: NIST Analyzer
nist_analyzer = Agent(
    role="NIST 800-53 Security Control Analyst",
    goal="Analyze NIST 800-53 security controls and extract their core security requirements, objectives, and implementation expectations in a structured format.",
    backstory="You are an expert in federal cybersecurity compliance with deep knowledge of NIST 800-53 Rev 5. You understand the intent behind each control family and can break down complex control language into clear, structured analysis.",
    llm=llm,
    verbose=False
)

# agent 2: CIS Analyzer
cis_analyzer = Agent(
    role="CIS Controls v8 Safeguard Analyst",
    goal="Analyze CIS Controls v8 safeguards and extract their implementation intent, technical requirements, and Implementation Group level in a structured format.",
    backstory="You are a cybersecurity practitioner with deep expertise in CIS Controls v8. You understand the practical implementation of each safeguard and how Implementation Groups (IG1, IG2, IG3) reflect organizational maturity levels.",
    llm=llm,
    verbose=False
)

# agent 3: Semantic Mapper -- now classifies results, doesn't search
semantic_mapper = Agent(
    role="Security Control Mapping Specialist",
    goal="Evaluate pre-identified CIS Controls v8 safeguards and assess the strength of their mapping to a given NIST 800-53 control.",
    backstory="You are a GRC specialist who understands both NIST and CIS frameworks deeply. You evaluate candidate mappings and classify them as STRONG, PARTIAL, or WEAK based on how well they address the NIST control's requirements. You ONLY evaluate safeguards provided to you -- you never add your own.",
    llm=llm,
    verbose=False
)

# agent 4: Mapping Interpreter -- no tools, pure writer
# Verification is now done in Python before this agent runs.
# All IDs in its prompt are pre-confirmed to exist in ChromaDB.
mapping_interpreter = Agent(
    role="Security Control Mapping Interpreter",
    goal="Generate clear, human-readable explanations for why NIST 800-53 controls map to specific CIS Controls v8 safeguards, providing auditable reasoning traces.",
    backstory="You are a compliance documentation specialist. You will be given a list of CIS safeguards that have already been verified to exist, along with their classifications. Write mapping explanations using ONLY the safeguards and classifications provided. Do not change any classification -- they are final.",
    llm=llm,
    verbose=False
)

print("All 4 agents initialized")

# ============================================================
# Pipeline function
# ============================================================

def run_mapping_pipeline(nist_control):
    """Run the full 4-agent pipeline for a single NIST control."""

    control_id = nist_control["id"]
    print(f"Processing {control_id}: {nist_control['title']}...")
    start_time = time.time()

    # semantic search happens in Python -- agents cannot hallucinate these results
    query_text = f"{nist_control['title']}. {nist_control['statement']}"
    query_embedding = embedder.encode(query_text).tolist()
    search_results = cis_collection.query(query_embeddings=[query_embedding], n_results=10)

    # pre-verify every ID from the search results directly in Python
    # ChromaDB cosine distance range is 0-2, so similarity = 1 - (distance / 2), giving 0.0-1.0
    raw_ids = search_results["ids"][0]
    verified_meta = verify_cis_ids(raw_ids)

    # build the verified mapping string -- only IDs confirmed in ChromaDB are included
    verified_mappings = ""
    count = 0
    for i in range(len(raw_ids)):
        cis_id = raw_ids[i]
        if cis_id not in verified_meta:
            continue  # skip any ID that didn't survive verification
        count += 1
        meta = verified_meta[cis_id]
        distance = search_results["distances"][0][i]
        similarity = round(1 - (distance / 2), 4)  # normalize cosine distance to 0-1
        verified_mappings += f"{count}. {cis_id}: {meta['title']}\n"
        verified_mappings += f"   Security Function: {meta['security_function']} | IG: {meta['lowest_ig']} | Similarity: {similarity}\n\n"

    print(f"  Semantic search complete -- {count} verified candidates (from {len(raw_ids)} raw results)")

    # task 1: NIST Analyzer
    task1 = Task(
        description=f"""Analyze the following NIST 800-53 control and provide a structured breakdown:
Control ID: {nist_control['id']}
Title: {nist_control['title']}
Family: {nist_control['family_title']}
Statement: {nist_control['statement']}
Guidance: {nist_control['guidance']}

Provide your analysis in this format:
1. SECURITY OBJECTIVE: What is this control trying to achieve?
2. KEY REQUIREMENTS: What must an organization do to comply?
3. IMPLEMENTATION SCOPE: What systems, processes, or personnel does this apply to?
4. RELATED SECURITY CONCEPTS: What broader security principles does this support?""",
        expected_output="A structured analysis of the NIST control.",
        agent=nist_analyzer
    )

    # task 2: Semantic Mapper -- classifies the pre-verified results
    task2 = Task(
        description=f"""Evaluate the following CIS Controls v8 safeguards that were found by semantic search as potential matches for NIST {nist_control['id']} ({nist_control['title']}).

THESE ARE THE ONLY CIS SAFEGUARDS TO EVALUATE. Do NOT add, invent, or reference any others:

{verified_mappings}

For EACH safeguard listed above, classify it as:
- STRONG mapping: directly addresses the same security requirement as {nist_control['id']}
- PARTIAL mapping: addresses some aspects but not all
- WEAK mapping: only tangentially related

Use the EXACT safeguard IDs shown above. Do NOT reference any safeguard not in this list.
Provide brief reasoning for each classification.""",
        expected_output="Classification of each listed CIS safeguard as STRONG, PARTIAL, or WEAK with reasoning.",
        agent=semantic_mapper
    )

    # phase 1: run agents 1 and 2
    crew_phase1 = Crew(
        agents=[nist_analyzer, semantic_mapper],
        tasks=[task1, task2],
        process=Process.sequential,
        verbose=False
    )
    crew_phase1.kickoff()

    mapping_raw = task2.output.raw if task2.output else ""
    nist_analysis_raw = task1.output.raw if task1.output else ""

    # task 3: CIS Analyzer
    task3 = Task(
        description=f"""Analyze the following CIS Controls v8 safeguards that were identified as matches for NIST {nist_control['id']}.

Here are the EXACT mapping results. Only analyze safeguards listed here:

{verified_mappings}

Classification from the mapping specialist:
{mapping_raw}

For each STRONG or PARTIAL safeguard, provide:
1. SAFEGUARD INTENT: What is this safeguard trying to accomplish?
2. TECHNICAL REQUIREMENTS: What specific technical actions must be taken?
3. IMPLEMENTATION CONTEXT: What maturity level (IG1/IG2/IG3) is this aimed at?
4. SECURITY FUNCTION ALIGNMENT: How does this safeguard's security function relate to its purpose?

Do NOT analyze or reference any safeguard that is not in the verified list above.""",
        expected_output="Structured analysis of each CIS safeguard from the verified mapping results.",
        agent=cis_analyzer
    )

    # task 4: Mapping Interpreter -- pure writer, no tools
    # All IDs below are pre-verified in Python. Classifications are FINAL -- do not change them.
    task4 = Task(
        description=f"""Generate a mapping explanation for NIST {nist_control['id']} ({nist_control['title']}).

NIST CONTROL ANALYSIS:
{nist_analysis_raw[:1500]}

VERIFIED CIS SAFEGUARD MAPPINGS:
The following safeguards have been confirmed to exist in the CIS Controls v8 database.
These are the ONLY safeguards you may reference -- do not add any others.
{verified_mappings}

FINAL CLASSIFICATIONS (these are fixed -- do not change them):
{mapping_raw[:1500]}

Write your explanation using ONLY the safeguards listed above, with EXACTLY the classifications shown.
Do not upgrade, downgrade, or re-evaluate any classification.

For each safeguard write:
1. WHY this mapping exists -- plain language explanation of the connection to {nist_control['id']}
2. WHAT ASPECTS of {nist_control['id']} this safeguard addresses
3. GAPS -- what parts of {nist_control['id']} this safeguard does NOT cover
4. For WEAK mappings, one sentence explaining why the connection is superficial

End with a COVERAGE SUMMARY:
- List the STRONG and PARTIAL safeguards only
- Estimate overall coverage percentage
- List the main remaining gaps in CIS coverage of {nist_control['id']}""",
        expected_output="Structured mapping explanations for each CIS safeguard using only the provided IDs and classifications.",
        agent=mapping_interpreter
    )

    # phase 2: run agents 3 and 4
    crew_phase2 = Crew(
        agents=[cis_analyzer, mapping_interpreter],
        tasks=[task3, task4],
        process=Process.sequential,
        verbose=False
    )
    result = crew_phase2.kickoff()

    elapsed = round(time.time() - start_time, 1)
    print(f"  Completed in {elapsed}s")

    return {
        "nist_id": control_id,
        "nist_title": nist_control["title"],
        "nist_family": nist_control["family_title"],
        "nist_analysis": nist_analysis_raw,
        "verified_search_results": verified_mappings,
        "mapping_classification": mapping_raw,
        "cis_analysis": task3.output.raw if task3.output else "",
        "interpretation": result.raw,
        "elapsed_seconds": elapsed
    }

print("Pipeline function ready -- semantic search is programmatic, no agent can hallucinate IDs")