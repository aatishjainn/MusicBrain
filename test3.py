import subprocess
import re
from typing import Optional, Dict, Any, List, Tuple

OLLAMA_MODEL = "mistral"

# Import your existing retriever helpers
from test import (
    parse_query,
    search_recordings,
    choose_best_recording,
    fetch_recording_relations,
    extract_credits,
)

# ---- Ollama CLI helper (utf-8 safe) ----
def generate_with_ollama_cli(prompt: str, model: str = OLLAMA_MODEL, timeout: int = 60) -> str:
    try:
        proc = subprocess.run(
            ["ollama", "run", model],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if proc.returncode != 0:
            err = proc.stderr.strip() if proc.stderr else "Unknown ollama error"
            raise RuntimeError(err)
        return proc.stdout.strip()
    except FileNotFoundError:
        raise RuntimeError("ollama CLI not found. Make sure 'ollama' is on PATH.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("ollama CLI timed out.")
    except Exception as e:
        raise RuntimeError(f"Ollama CLI failure: {e}")

# show top-3 candidates and allow user to pick
def list_top_candidates(search_res: dict, title_query: str, artist_query: Optional[str]) -> List[dict]:
    """
    Return up to top-3 recordings from the search result, ordered by choose_best heuristics.
    """
    recs = search_res.get("recordings", []) or []
    # compute simple score by similarity to title and artist (reuse choose_best_recording heuristics)
    # We'll reuse choose_best_recording to find the best; then remove and repeat to get top3.
    candidates = []
    remaining = {"recordings": recs}
    # build a copy list to iterate
    rec_list = list(recs)
    # Use the provided choose_best_recording function repeatedly to pick top N
    for _ in range(min(3, len(rec_list))):
        best = None
        best_score = -1.0
        for r in rec_list:
            # compute score similar to choose_best_recording implementation
            rtitle = r.get("title", "")
            artist_names = " ".join([ac.get("name","") for ac in r.get("artist-credit", [])])
            # approximate similarity using simple lower-case substring matches and lengths
            score = 0.0
            if title_query and rtitle:
                if title_query.lower() == rtitle.lower():
                    score += 0.7
                elif title_query.lower() in rtitle.lower() or rtitle.lower() in title_query.lower():
                    score += 0.5
            if artist_query:
                if artist_query.lower() in artist_names.lower() or artist_names.lower() in artist_query.lower():
                    score += 0.3
            # small boost if release present
            if r.get("releases"):
                score += 0.01
            if score > best_score:
                best_score = score
                best = r
        if best:
            candidates.append(best)
            rec_list.remove(best)
        else:
            break
    return candidates

def pretty_candidate_line(idx: int, r: dict) -> str:
    title = r.get("title", "Unknown")
    ac = r.get("artist-credit", [])
    artists = ", ".join([a.get("name","") for a in ac]) if ac else "Unknown"
    rels = r.get("releases") or []
    rel_str = ""
    if rels:
        rel = rels[0]
        rel_title = rel.get("title") or ""
        rel_date = rel.get("date") or ""
        rel_str = f"{rel_title}" + (f" ({rel_date})" if rel_date else "")
    mbid = r.get("id")
    return f"{idx}. \"{title}\" — {artists}" + (f" | Release: {rel_str}" if rel_str else "") + f" | MBID: {mbid}"

def choose_candidate_interactively(search_res: dict, title: str, artist: Optional[str]) -> Optional[dict]:
    """
    If multiple candidates exist, present top-3 and let the user pick.
    Returns chosen recording dict or None if none chosen.
    """
    recs = search_res.get("recordings", []) or []
    if not recs:
        return None
    # If only one result, return it
    if len(recs) == 1:
        return recs[0]
    # prepare top-3 list
    candidates = list_top_candidates(search_res, title, artist)
    if not candidates:
        # fallback: return first recording
        return recs[0]
    # show candidates
    print("\nMultiple possible recordings found — please choose which one you mean:")
    for i, c in enumerate(candidates, start=1):
        print(pretty_candidate_line(i, c))
    print("Enter 1/2/3 to choose, 'c' to cancel, or press Enter to pick #1.")
    while True:
        choice = input("Choice [1]: ").strip().lower()
        if choice == "":
            return candidates[0]
        if choice == "c":
            return None
        if choice in ("1","2","3"):
            idx = int(choice) - 1
            if idx < len(candidates):
                return candidates[idx]
            else:
                print("Invalid selection (not present in list). Try again.")
        else:
            print("Invalid input. Enter 1,2,3, c, or Enter for default.")

# ---- retrieval wrapper that uses chooser ----
def retrieve_with_choice(title: str, artist: Optional[str]=None) -> Optional[Dict[str, Any]]:
    """
    Search and, if multiple matches, let user pick. Return full extracted info dict.
    """
    try:
        # do a search query (we'll examine recordings list)
        search_res = search_recordings(title, artist, limit=10)
    except Exception as e:
        print(f"Search error: {e}")
        return None

    # If no recordings found, return None
    recs = search_res.get("recordings", []) or []
    if not recs:
        return None

    # If multiple recordings -> interactive chooser
    chosen_recording = None
    if len(recs) > 1:
        chosen_recording = choose_candidate_interactively(search_res, title, artist)
        if not chosen_recording:
            # user canceled
            return None
    else:
        chosen_recording = recs[0]

    # fetch full relations for chosen MBID
    mbid = chosen_recording.get("id")
    try:
        full = fetch_recording_relations(mbid)
        info = extract_credits(full)
        # attach mbid for traceability
        info["_mbid"] = mbid
        return info
    except Exception as e:
        print(f"Error fetching recording details: {e}")
        return None

# ---- deterministic check for producer presence ----
def deterministic_producer_check(info: Dict[str,Any], artist_query: str) -> Optional[bool]:
    if not info:
        return None
    producers = info.get("credits", {}).get("producer", []) or []
    if not producers:
        return None
    aq = artist_query.lower().strip()
    for p in producers:
        if p and p.lower().strip() == aq:
            return True
    for p in producers:
        if p and aq in p.lower():
            return True
    return False

# ---- build short context for LLM ----
def build_context_from_info(info: Dict[str,Any]) -> str:
    lines = []
    t = info.get("title") or "Unknown title"
    lines.append(f"Title: {t}")
    artists = info.get("artists") or []
    if artists:
        lines.append("Artist(s): " + ", ".join(artists))
    if info.get("release_title") or info.get("release_date"):
        rel = info.get("release_title") or ""
        date = info.get("release_date") or ""
        lines.append("Release: " + (f"{rel} ({date})" if date else rel))
    if info.get("length_ms"):
        secs = int(info["length_ms"] // 1000)
        lines.append(f"Duration_seconds: {secs}")
    credits = info.get("credits", {}) or {}
    for role in ("composer", "lyricist", "producer", "performer"):
        vals = credits.get(role) or []
        if vals:
            # dedupe
            seen = []
            out = []
            for v in vals:
                if v and v not in seen:
                    seen.append(v); out.append(v)
            lines.append(f"{role.capitalize()}: " + ", ".join(out))
    if info.get("_mbid"):
        lines.append(f"MBID: {info.get('_mbid')}")
    return "\n".join(lines)

# ---- LLM prompt templates ----
SYSTEM_INSTRUCTION = (
    "You are a helpful music assistant. Use ONLY the factual context provided below to answer the user. "
    "If the context does not include evidence for the user's claim, say you don't have evidence. Keep answers concise and friendly."
)

def compose_prompt_general(context: str, question: str) -> str:
    return f"{SYSTEM_INSTRUCTION}\n\nFACTS:\n{context}\n\nUSER QUESTION: {question}\n\nAnswer in 1-3 concise sentences using only the facts."

def compose_prompt_yesno(context: str, question: str, yes: bool) -> str:
    if yes:
        instr = "Confirm the claim politely and mention the producer(s) from the facts."
    else:
        instr = "Politely explain that the facts do not support the claim and list the producers present in the facts."
    return f"{SYSTEM_INSTRUCTION}\n\nFACTS:\n{context}\n\nUSER QUESTION: {question}\n\n{instr}\n\nAnswer in 1-2 concise, conversational sentences."

def compose_prompt_no_producer(context: str, question: str) -> str:
    return f"{SYSTEM_INSTRUCTION}\n\nFACTS:\n{context}\n\nUSER QUESTION: {question}\n\nThe facts do not include producer information. Respond conversationally saying you don't have evidence and avoid guessing."

# ---- yes/no producer question parser (simple heuristics) ----
def parse_yesno_producer_question(q: str) -> Optional[Dict[str,str]]:
    s = q.strip().rstrip("?").strip()
    patterns = [
        r'^\s*is\s+["\']?(?P<title>.+?)["\']?\s+produced\s+by\s+["\']?(?P<artist>.+?)["\']?\s*$',
        r'^\s*was\s+["\']?(?P<title>.+?)["\']?\s+produced\s+by\s+["\']?(?P<artist>.+?)["\']?\s*$',
        r'^\s*did\s+["\']?(?P<artist>.+?)["\']?\s+produce\s+["\']?(?P<title>.+?)["\']?\s*$',
        r'^\s*is\s+["\']?(?P<artist>.+?)["\']?\s+(the\s+)?producer\s+of\s+["\']?(?P<title>.+?)["\']?\s*$',
    ]
    for p in patterns:
        m = re.search(p, s, flags=re.IGNORECASE)
        if m:
            return {"song": m.group("title").strip(), "artist": m.group("artist").strip()}
    return None

def split_title_and_perf(maybe_title: str) -> Tuple[str, Optional[str]]:
    parts = re.split(r'\s+by\s+', maybe_title, flags=re.IGNORECASE)
    if len(parts) >= 2:
        return parts[0].strip(), parts[1].strip()
    return maybe_title.strip(), None

# ---- Interactive CLI ----
def interactive_loop():
    print("MusicBrainz CLI with top-3 candidate chooser")
    print("Examples: 'Tell me about Bohemian Rhapsody by Queen'  |  'Is Skeletons by Travis Scott produced by Tame Impala?'")
    print("Commands: help, exit, quit\n")

    while True:
        try:
            user_input = input(">> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break
        if not user_input:
            continue
        lc = user_input.lower().strip()
        if lc in ("exit", "quit"):
            print("Goodbye!"); break
        if lc in ("help", "?"):
            print("Ask about a song or credits. Examples:")
            print("  Tell me about Bohemian Rhapsody by Queen")
            print("  Is Skeletons by Travis Scott produced by Tame Impala?")
            continue

        # first detect yes/no producer checks
        yesno = parse_yesno_producer_question(user_input)
        if yesno:
            raw_song = yesno["song"]
            prod_candidate = yesno["artist"]
            title, performer_hint = split_title_and_perf(raw_song)
            # attempt retrieval with chooser
            info = None
            if performer_hint:
                info = retrieve_with_choice(title, performer_hint)
            if not info:
                info = retrieve_with_choice(title, None)
            if not info:
                print("No matching recording found on MusicBrainz.")
                continue
            det = deterministic_producer_check(info, prod_candidate)
            context = build_context_from_info(info)
            try:
                if det is True:
                    prompt = compose_prompt_yesno(context, user_input, yes=True)
                    out = generate_with_ollama_cli(prompt, OLLAMA_MODEL)
                    print("\n" + out.strip() + f"\n\n(Facts: producers = {', '.join(info.get('credits', {}).get('producer', []) or ['N/A'])})\n")
                elif det is False:
                    prompt = compose_prompt_yesno(context, user_input, yes=False)
                    out = generate_with_ollama_cli(prompt, OLLAMA_MODEL)
                    print("\n" + out.strip() + f"\n\n(Facts: producers = {', '.join(info.get('credits', {}).get('producer', []) or ['N/A'])})\n")
                else:
                    prompt = compose_prompt_no_producer(context, user_input)
                    out = generate_with_ollama_cli(prompt, OLLAMA_MODEL)
                    print("\n" + out.strip() + f"\n\n(Facts: producers not available)\n")
            except Exception as e:
                # fallback deterministic
                if det is True:
                    prods = info.get("credits", {}).get("producer", [])
                    print(f"Yes — MusicBrainz lists these producers for \"{info.get('title','?')}\": {', '.join(prods)}.")
                elif det is False:
                    prods = info.get("credits", {}).get("producer", [])
                    print(f"No — MusicBrainz lists these producers for \"{info.get('title','?')}\": {', '.join(prods)}.")
                else:
                    print("MusicBrainz does not have producer credit information for that track.")
            continue

        # otherwise general info request
        parsed = parse_query(user_input)
        title = parsed.get("title")
        artist = parsed.get("artist")
        if not title:
            print("Couldn't extract a song title. Try: Tell me about Shape of You by Ed Sheeran")
            continue

        info = None
        if artist:
            info = retrieve_with_choice(title, artist)
        if not info:
            info = retrieve_with_choice(title, None)
        if not info:
            print("No matching recording found on MusicBrainz.")
            continue

        # build context and call LLM
        context = build_context_from_info(info)
        prompt = compose_prompt_general(context, user_input)
        try:
            answer = generate_with_ollama_cli(prompt, OLLAMA_MODEL)
            footer = f"\n\n(Facts sourced from MusicBrainz: MBID = {info.get('_mbid')})"
            print("\n" + answer.strip() + footer + "\n")
        except Exception as e:
            print(f"LLM generation failed: {e}\nFalling back to raw facts:\n")
            print(context + "\n")

if __name__ == "__main__":
    interactive_loop()
