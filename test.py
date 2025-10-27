import requests
import time
import re
from difflib import SequenceMatcher
from typing import Optional, Dict, Any

MB_BASE = "https://musicbrainz.org/ws/2"
USER_AGENT = "MyMusicChatbot/0.1 ( aatishjainn@gmail.com )"  # ← replace with your app + contact

# Respect simple rate-limit (1 req / sec). For production, use a proper rate limiter.
_last_request_time = 0.0
def _throttle():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_request_time = time.time()

def parse_query(text: str) -> Dict[str, Optional[str]]:
    """
    Try to extract (title, artist) from user text using common patterns.
    Fallback: return entire text as title and None as artist.
    """
    t = text.strip().lower()
    # common patterns: "tell me about <title> by <artist>"
    patterns = [
        r"tell me about\s+['\"]?(?P<title>.+?)['\"]?\s+by\s+(?P<artist>.+)",
        r"about\s+['\"]?(?P<title>.+?)['\"]?\s+by\s+(?P<artist>.+)",
        r"what can you tell me about\s+['\"]?(?P<title>.+?)['\"]?\s+by\s+(?P<artist>.+)",
        r"(?P<title>.+?)\s+by\s+(?P<artist>.+)",  # fallback generic "<title> by <artist>"
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            title = m.group("title").strip()
            artist = m.group("artist").strip()
            return {"title": title, "artist": artist}
    # If not found, try "by" split
    if " by " in text.lower():
        parts = text.split(" by ", 1)
        return {"title": parts[0].strip(), "artist": parts[1].strip()}
    # last fallback: assume whole text is title
    return {"title": text.strip(), "artist": None}

def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()

def search_recordings(title: str, artist: Optional[str]=None, limit:int=10) -> Any:
    """
    Query MusicBrainz recordings search.
    """
    _throttle()
    q = f'recording:"{title}"'
    if artist:
        q += f' AND artist:"{artist}"'
    params = {"query": q, "fmt": "json", "limit": str(limit)}
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(f"{MB_BASE}/recording/", params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()

def choose_best_recording(results: dict, title: str, artist: Optional[str]=None) -> Optional[dict]:
    """
    Pick the best candidate using simple similarity heuristics on title and artist-credit.
    """
    recordings = results.get("recordings", [])
    best = None
    best_score = 0.0
    for r in recordings:
        rtitle = r.get("title", "")
        # combine artist-credit names if available
        artist_names = " ".join([ac.get("name","") for ac in r.get("artist-credit", [])])
        score = 0.0
        score += 0.6 * _similar(title, rtitle)
        if artist:
            score += 0.4 * _similar(artist, artist_names)
        # boost exact MBID match? (not used here)
        if score > best_score:
            best_score = score
            best = r
    return best

def fetch_recording_relations(mbid: str) -> dict:
    """
    Fetch recording including relationships (works, artist-relationships). Use inc=artist-credits+releases+work-rels
    """
    _throttle()
    params = {"fmt": "json", "inc": "artist-credits+releases+work-rels+recording-rels+artist-rels"}
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(f"{MB_BASE}/recording/{mbid}", params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()

def extract_credits(recording_json: dict) -> dict:
    """
    Extract useful info: title, artists, releases, length, and relations like composer/producer/writer.
    """
    info = {}
    info["title"] = recording_json.get("title")
    info["length_ms"] = recording_json.get("length")
    # artists
    info["artists"] = [ac.get("name") for ac in recording_json.get("artist-credit", []) if ac.get("name")]
    # releases
    releases = recording_json.get("releases", []) or []
    if releases:
        # choose earliest release by date if present
        releases_sorted = sorted(releases, key=lambda r: r.get("date") or "9999-99-99")
        info["release_title"] = releases_sorted[0].get("title")
        info["release_date"] = releases_sorted[0].get("date")
    else:
        info["release_title"] = None
        info["release_date"] = None
    # relations -> find composers, lyricists, producers
    relations = recording_json.get("relations", []) or recording_json.get("relation-list", []) or []
    credits = {"composer": [], "lyricist": [], "producer": [], "performer": []}
    for rel in relations:
        rtype = rel.get("type", "").lower()
        # artist nested either at rel['artist'] or rel.get('target-credit')
        artist_name = None
        if rel.get("artist"):
            artist_name = rel["artist"].get("name")
        elif rel.get("target-credit"):
            artist_name = rel.get("target-credit")
        elif rel.get("target"):
            artist_name = rel.get("target")
        if not artist_name:
            continue
        if "compose" in rtype or "composer" in rtype or "written" in rtype:
            credits["composer"].append(artist_name)
        if "lyric" in rtype:
            credits["lyricist"].append(artist_name)
        if "produce" in rtype or "producer" in rtype:
            credits["producer"].append(artist_name)
        if "performer" in rtype or "perform" in rtype:
            credits["performer"].append(artist_name)
    info["credits"] = credits
    return info

def format_response(info: dict) -> str:
    """
    Build a conversational message from extracted info.
    """
    if not info:
        return "Sorry — I couldn't find details for that song."
    parts = []
    parts.append(f"**{info.get('title','Unknown title')}**")
    if info.get("artists"):
        parts.append("by " + ", ".join(info["artists"]))
    if info.get("release_title") or info.get("release_date"):
        rel = info.get("release_title") or ""
        date = info.get("release_date") or ""
        parts.append(f"Released: {rel}" + (f" ({date})" if date else ""))
    credits = info.get("credits", {})
    credit_lines = []
    if credits.get("composer"):
        credit_lines.append("Written by: " + ", ".join(dict.fromkeys(credits["composer"])))
    if credits.get("producer"):
        credit_lines.append("Produced by: " + ", ".join(dict.fromkeys(credits["producer"])))
    if credits.get("lyricist"):
        credit_lines.append("Lyrics: " + ", ".join(dict.fromkeys(credits["lyricist"])))
    if credit_lines:
        parts.append(" | ".join(credit_lines))
    if info.get("length_ms"):
        secs = int(info["length_ms"] // 1000)
        parts.append(f"Duration: {secs//60}:{secs%60:02d}")
    return "\n".join(parts)

# High-level convenience function
def get_song_info_from_text(user_text: str) -> str:
    parsed = parse_query(user_text)
    title = parsed["title"]
    artist = parsed["artist"]
    if not title:
        return "I couldn't extract a song title from your message. Try 'Tell me about Shape of You by Ed Sheeran'."
    try:
        search_res = search_recordings(title, artist, limit=8)
        candidate = choose_best_recording(search_res, title, artist)
        if not candidate:
            return "No matching recording found on MusicBrainz."
        mbid = candidate.get("id")
        full = fetch_recording_relations(mbid)
        info = extract_credits(full)
        return format_response(info)
    except requests.HTTPError as e:
        return f"MusicBrainz API error: {e}"
    except Exception as e:
        return f"Error: {e}"

# Example quick test
# musicbrainz_retriever_cli.py
# (Keep the rest of the functions from your original musicbrainz_retriever.py above this block)

if __name__ == "__main__":
    print("MusicBrainz Retriever CLI — interactive mode")
    print("Type a query like: Tell me about Bohemian Rhapsody by Queen")
    print("Commands: 'exit', 'quit', 'help', 'examples'\n")

    examples = [
        "Tell me about Bohemian Rhapsody by Queen",
        "Shape of You by Ed Sheeran",
        "Nothing Else Matters Metallica"
    ]

    while True:
        try:
            user_input = input(">> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting. Bye!")
            break

        if not user_input:
            continue

        cmd = user_input.lower().strip()
        if cmd in ("exit", "quit"):
            print("Goodbye!")
            break
        if cmd == "help":
            print("Enter a natural language query for a song. Examples:")
            for ex in examples:
                print("  -", ex)
            print("Commands: 'exit', 'quit', 'help', 'examples'\n")
            continue
        if cmd == "examples":
            print("Examples:")
            for ex in examples:
                print("  -", ex)
            continue

        # Call the main high-level function from the rest of the file
        try:
            response = get_song_info_from_text(user_input)
            print("\n" + response + "\n")
        except Exception as e:
            print(f"Error while getting song info: {e}\n")
