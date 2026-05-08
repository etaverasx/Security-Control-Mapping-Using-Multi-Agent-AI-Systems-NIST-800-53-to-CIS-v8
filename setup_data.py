# setup_data.py
# Run this ONCE to download data, parse controls, generate embeddings, and build ChromaDB.
# After the first run, everything persists on disk -- no need to run again unless rebuilding.
#
# IMPORTANT: If you need to rebuild ChromaDB (e.g., after changing the distance metric),
# delete the chromadb folder first, then re-run this script.

import json
import os
import urllib.request
import openpyxl
from collections import Counter
from sentence_transformers import SentenceTransformer
import chromadb

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_PATH, "data")
CHROMADB_PATH = os.path.join(BASE_PATH, "chromadb")

# create folders if they don't exist
for folder in [DATA_PATH, CHROMADB_PATH, "outputs", "test_runs", "full_runs"]:
    os.makedirs(os.path.join(BASE_PATH, folder), exist_ok=True)

print("Folders ready")

# ============================================================
# STEP 1: Download and parse NIST 800-53 Rev 5
# ============================================================

nist_file = os.path.join(DATA_PATH, "nist_800_53_rev5.json")

if not os.path.exists(nist_file):
    print("Downloading NIST 800-53 Rev 5 catalog...")
    nist_url = "https://raw.githubusercontent.com/usnistgov/oscal-content/main/nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json"
    urllib.request.urlretrieve(nist_url, nist_file)
    print("Downloaded")
else:
    print("NIST data already exists, skipping download")

with open(nist_file, "r") as f:
    nist_raw = json.load(f)

groups = nist_raw["catalog"]["groups"]

def extract_controls(groups):
    controls = []
    for group in groups:
        family_id = group["id"].upper()
        family_title = group["title"]
        for control in group.get("controls", []):
            control_data = parse_control(control, family_id, family_title)
            controls.append(control_data)
            for enhancement in control.get("controls", []):
                enh_data = parse_control(enhancement, family_id, family_title)
                controls.append(enh_data)
    return controls

def parse_control(control, family_id, family_title):
    statement = ""
    guidance = ""
    for part in control.get("parts", []):
        if part["name"] == "statement":
            statement = extract_prose(part)
        elif part["name"] == "guidance":
            guidance = extract_prose(part)
    return {
        "id": control["id"].upper(),
        "title": control.get("title", ""),
        "family_id": family_id,
        "family_title": family_title,
        "statement": statement,
        "guidance": guidance,
        "framework": "NIST 800-53"
    }

def extract_prose(part):
    text = part.get("prose", "")
    for sub in part.get("parts", []):
        sub_text = extract_prose(sub)
        if sub_text:
            text += " " + sub_text
    return text.strip()

nist_controls = extract_controls(groups)
print(f"NIST controls extracted: {len(nist_controls)}")

# save parsed NIST controls as JSON for other scripts to load
nist_parsed_file = os.path.join(DATA_PATH, "nist_controls_parsed.json")
with open(nist_parsed_file, "w") as f:
    json.dump(nist_controls, f, indent=2)
print(f"Saved parsed NIST controls to {nist_parsed_file}")

# ============================================================
# STEP 2: Parse CIS Controls v8
# ============================================================

cis_file = os.path.join(DATA_PATH, "CIS_Controls_Version_8.xlsx")

if not os.path.exists(cis_file):
    print(f"ERROR: CIS spreadsheet not found at {cis_file}")
    print("Please copy CIS_Controls_Version_8.xlsx into the data folder")
    exit(1)

wb = openpyxl.load_workbook(cis_file)
ws = wb["Controls V8"]

cis_controls = []
cis_safeguards = []

for row in ws.iter_rows(min_row=2, values_only=True):
    cis_control, cis_safeguard, asset_type, sec_function, title, description, ig1, ig2, ig3 = row
    control_num = str(cis_control).strip().replace("\xa0", "") if cis_control else None

    if cis_safeguard is None and title is not None:
        cis_controls.append({
            "control_number": control_num,
            "title": title,
            "description": description
        })
    elif cis_safeguard is not None:
        if ig1 == "x":
            lowest_ig = "IG1"
        elif ig2 == "x":
            lowest_ig = "IG2"
        else:
            lowest_ig = "IG3"

        cis_safeguards.append({
            "id": f"CIS {cis_safeguard}",
            "control_number": control_num,
            "title": title,
            "description": description,
            "asset_type": asset_type,
            "security_function": sec_function,
            "ig1": ig1 == "x",
            "ig2": ig2 == "x",
            "ig3": ig3 == "x",
            "lowest_ig": lowest_ig,
            "framework": "CIS Controls v8"
        })

# fix duplicate IDs where spreadsheet dropped trailing zeros
fix_map = {
    "Encrypt Sensitive Data in Transit": "CIS 3.10",
    "Enforce Automatic Device Lockout on Portable End-User Devices": "CIS 4.10",
    "Retain Audit Logs": "CIS 8.10",
    "Perform Application Layer Filtering": "CIS 13.10",
    "Apply Secure Design Principles in Application Architectures": "CIS 16.10"
}

for s in cis_safeguards:
    if s["title"] in fix_map:
        s["id"] = fix_map[s["title"]]

# verify no duplicates
id_counts = Counter(s["id"] for s in cis_safeguards)
dupes = {k: v for k, v in id_counts.items() if v > 1}
if dupes:
    print(f"WARNING: {len(dupes)} duplicate CIS IDs found: {dupes}")
else:
    print(f"CIS safeguards parsed: {len(cis_safeguards)} (no duplicates)")

# show security function breakdown
sec_functions = Counter(s["security_function"] for s in cis_safeguards)
print("Security Functions:")
for func, count in sec_functions.most_common():
    print(f"  {func}: {count}")

# save parsed CIS safeguards as JSON for other scripts to load
cis_parsed_file = os.path.join(DATA_PATH, "cis_safeguards_parsed.json")
with open(cis_parsed_file, "w") as f:
    json.dump(cis_safeguards, f, indent=2)
print(f"Saved parsed CIS safeguards to {cis_parsed_file}")

# ============================================================
# STEP 3: Build ChromaDB with embeddings (using cosine distance)
# ============================================================

print("\nLoading embedding model...")
embedder = SentenceTransformer("all-MiniLM-L6-v2")
print(f"Embedding model loaded, dimension: {embedder.get_sentence_embedding_dimension()}")

chroma_client = chromadb.PersistentClient(path=CHROMADB_PATH)

# use cosine distance -- the correct metric for sentence-transformer embeddings
# cosine measures the angle between vectors, which captures semantic similarity
# ChromaDB stores this as 1 - cosine_similarity, so 0 = identical, 2 = opposite
DISTANCE_METRIC = {"hnsw:space": "cosine"}

nist_collection = chroma_client.get_or_create_collection(name="nist_800_53", metadata={"hnsw:space": "cosine"})
cis_collection = chroma_client.get_or_create_collection(name="cis_controls_v8", metadata={"hnsw:space": "cosine"})

if nist_collection.count() == 0:
    print("Generating NIST embeddings...")
    nist_docs = []
    nist_ids = []
    nist_metadatas = []
    for c in nist_controls:
        text = f"{c['title']}. {c['statement']} {c['guidance']}"
        nist_docs.append(text)
        nist_ids.append(c["id"])
        nist_metadatas.append({
            "framework": "NIST 800-53",
            "family_id": c["family_id"],
            "family_title": c["family_title"],
            "title": c["title"]
        })
    nist_embeddings = embedder.encode(nist_docs, show_progress_bar=True).tolist()
    nist_collection.add(documents=nist_docs, embeddings=nist_embeddings, ids=nist_ids, metadatas=nist_metadatas)
    print(f"  NIST collection loaded: {nist_collection.count()} controls")
else:
    print(f"  NIST collection already exists: {nist_collection.count()} controls")

if cis_collection.count() == 0:
    print("Generating CIS embeddings...")
    cis_docs = []
    cis_ids = []
    cis_metadatas = []
    for s in cis_safeguards:
        text = f"{s['title']}. {s['description']}"
        cis_docs.append(text)
        cis_ids.append(s["id"])
        cis_metadatas.append({
            "framework": "CIS Controls v8",
            "control_number": s["control_number"],
            "title": s["title"],
            "asset_type": s["asset_type"],
            "security_function": s["security_function"],
            "lowest_ig": s["lowest_ig"],
            "ig1": str(s["ig1"]),
            "ig2": str(s["ig2"]),
            "ig3": str(s["ig3"])
        })
    cis_embeddings = embedder.encode(cis_docs, show_progress_bar=True).tolist()
    cis_collection.add(documents=cis_docs, embeddings=cis_embeddings, ids=cis_ids, metadatas=cis_metadatas)
    print(f"  CIS collection loaded: {cis_collection.count()} safeguards")
else:
    print(f"  CIS collection already exists: {cis_collection.count()} safeguards")

# quick semantic search test to verify cosine similarity works
print("\nTesting semantic search (cosine distance)...")
test_query = "Account Management. Manage system accounts, group memberships, access authorizations."
test_embedding = embedder.encode(test_query).tolist()
test_results = cis_collection.query(query_embeddings=[test_embedding], n_results=5)
print(f"Query: {test_query}")
print("Top 5 matches:")
for i in range(5):
    cis_id = test_results["ids"][0][i]
    title = test_results["metadatas"][0][i]["title"]
    distance = test_results["distances"][0][i]
    similarity = round(1 - distance, 4)
    print(f"  {cis_id}: {title} | Similarity: {similarity}")

print("\n=== SETUP COMPLETE ===")