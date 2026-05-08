# clean_and_verify.py
# Run this BEFORE setup_data.py when rebuilding from scratch.
# Deletes ChromaDB, all __pycache__ folders, and .pyc files,
# then verifies cosine distance is working after you re-run setup_data.py.
#
# Usage:
#   Step 1: python clean_and_verify.py --clean
#   Step 2: python setup_data.py
#   Step 3: python clean_and_verify.py --verify

import os
import sys
import shutil
import argparse

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
CHROMADB_PATH = os.path.join(BASE_PATH, "chromadb")

def clean():
    removed = []

    # remove chromadb folder
    if os.path.exists(CHROMADB_PATH):
        shutil.rmtree(CHROMADB_PATH)
        removed.append(f"  chromadb/  ({CHROMADB_PATH})")
    else:
        print("  chromadb/ not found -- already clean")

    # remove all __pycache__ folders
    for root, dirs, files in os.walk(BASE_PATH):
        for d in dirs:
            if d == "__pycache__":
                full = os.path.join(root, d)
                shutil.rmtree(full)
                removed.append(f"  __pycache__/  ({full})")

    # remove all .pyc files (in case any escaped __pycache__)
    for root, dirs, files in os.walk(BASE_PATH):
        for f in files:
            if f.endswith(".pyc"):
                full = os.path.join(root, f)
                os.remove(full)
                removed.append(f"  {f}  ({full})")

    if removed:
        print("Removed:")
        for r in removed:
            print(r)
    print("\nClean complete. Now run: python setup_data.py")


def verify():
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        print(f"ERROR: missing package -- {e}")
        sys.exit(1)

    if not os.path.exists(CHROMADB_PATH):
        print("ERROR: chromadb/ folder not found.")
        print("Run setup_data.py first, then re-run this script with --verify")
        sys.exit(1)

    print("Connecting to ChromaDB...")
    client = chromadb.PersistentClient(path=CHROMADB_PATH)

    # check both collections exist and have cosine metadata
    print("\n--- Collection check ---")
    all_ok = True
    for name in ["nist_800_53", "cis_controls_v8"]:
        try:
            col = client.get_collection(name)
            meta = col.metadata
            count = col.count()
            space = meta.get("hnsw:space", "NOT SET") if meta else "NOT SET"
            status = "OK" if space == "cosine" else "WRONG"
            print(f"  {name}: {count} items | distance metric: {space} [{status}]")
            if space != "cosine":
                all_ok = False
                print(f"    FIX: delete chromadb/ and re-run setup_data.py")
        except Exception as e:
            print(f"  {name}: ERROR -- {e}")
            all_ok = False

    if not all_ok:
        print("\nVerification FAILED -- fix the issues above before running the pipeline.")
        sys.exit(1)

    # run a similarity test with a known account management query
    print("\n--- Similarity score check ---")
    print("Loading embedding model...")
    embedder = SentenceTransformer("all-MiniLM-L6-v2")
    cis_col = client.get_collection("cis_controls_v8")

    query = "Account Management. Manage system accounts, group memberships, access authorizations."
    embedding = embedder.encode(query).tolist()
    results = cis_col.query(query_embeddings=[embedding], n_results=5)

    print(f"Query: {query}")
    print("\nTop 5 results (similarity should be 0.0-1.0, higher = more similar):")
    scores_ok = True
    for i in range(len(results["ids"][0])):
        cis_id = results["ids"][0][i]
        title = results["metadatas"][0][i]["title"]
        distance = results["distances"][0][i]
        similarity = round(1 - (distance / 2), 4)  # cosine: 0-2 range -> 0-1
        flag = ""
        if similarity < 0 or similarity > 1:
            flag = "  <-- BAD: out of range"
            scores_ok = False
        print(f"  {cis_id}: {title}")
        print(f"    distance={round(distance,4)}  similarity={similarity}{flag}")

    print()
    if scores_ok:
        print("Verification PASSED -- cosine distance is working correctly.")
        print("Similarity scores are in the expected 0.0-1.0 range.")
        print("\nReady to run: python test_pipeline.py")
    else:
        print("Verification FAILED -- similarity scores are out of range.")
        print("Delete chromadb/ and re-run setup_data.py.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean and verify ChromaDB setup")
    parser.add_argument("--clean", action="store_true", help="Delete chromadb/ and all __pycache__")
    parser.add_argument("--verify", action="store_true", help="Verify cosine distance after setup_data.py")
    args = parser.parse_args()

    if args.clean:
        print("=== CLEAN ===")
        clean()
    elif args.verify:
        print("=== VERIFY ===")
        verify()
    else:
        parser.print_help()
