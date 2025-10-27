# **MusicBrainz + Ollama CLI Assistant**

MusicBrainz + Ollama CLI Assistant\
\
A command-line music information assistant that combines the MusicBrainz API with a local LLM (Mistral) through Ollama.\
It retrieves factual song metadata (credits, producers, composers, releases, etc.) and uses the LLM to respond conversationally — while staying grounded in verified MusicBrainz data.\
\
\
**Features**\
\
\- Retrieve detailed song information from MusicBrainz\
\- Generate natural, conversational answers using a local LLM (via Ollama)\
\- Ask yes/no producer questions (e.g. “Is Skeletons by Travis Scott produced by Tame Impala?”)\
\- Interactive top-3 candidate chooser for ambiguous queries\
\- Deterministic fallback logic (works even if the LLM or Ollama fails)\
\- Simple command-line interface — type queries naturally\
\
\
**Project Structure**\
musicbrainz-cli/\
├── test.py             # MusicBrainz retriever (searches, fetches, parses API responses)\
├── test3.py            # CLI assistant integrating Ollama + top-3 chooser\
└── README.docx          

**Requirements**\
System:\
\- Python 3.8+\
\- Ollama installed and added to your system PATH (used to run the local LLM, e.g. mistral)\
\
Python packages:\
pip install requests\
\
Setup\
1\. Clone the repository:\
`   `git clone https://github.com/aatishjainn/musicbrains.git\
`   `cd musicbrains\
\
2\. Ensure Ollama is installed and a model is available:\
`   `ollama list\
`   `ollama pull mistral\
\
3\. (Optional) Update User-Agent in test.py:\
`   `USER\_AGENT = "MyMusicChatbot/0.1 ( your\_email@example.com )"\
\
\------------------------------------------------------------\
Usage\
\------------------------------------------------------------\
Option 1 — Direct Retriever\
python test.py\
\
Example:\
\*\*Shape of You\*\*\
by Ed Sheeran\
Released: Single Release (2017-01-06)\
Written by: Ed Sheeran | Produced by: Steve Mac, Johnny McDaid | Lyrics: Ed Sheeran\
Duration: 3:53\
\
Option 2 — Full Assistant (with LLM and top-3 chooser)\
python test3.py\
\
Example session:\
MusicBrainz CLI with top-3 candidate chooser\
Examples: 'Tell me about Bohemian Rhapsody by Queen' | 'Is Skeletons by Travis Scott produced by Tame Impala?'\
\
✅ Yes — MusicBrainz lists these producers for "Skeletons": Kevin Parker (Tame Impala), Mike Dean, Kanye West.\
\
` `**How It Works**\
1\. Parse query → extract title & artist\
2\. Search MusicBrainz API for recordings\
3\. Rank and display top-3 matches\
4\. Let user select the correct one\
5\. Fetch full relationships for MBID\
6\. Build structured “facts” context\
7\. Send to Ollama (Mistral) for conversational response\
8\. Output concise, fact-based answer\
\
**License**\
MIT License © 2025 Aatish Jain\
\
**Author**\
Developed by Aatish Jain\
aatishjainn@gmail.com\
\
**Acknowledgements:**\
\- MusicBrainz — open music metadata database\
\- Ollama — local LLM runtime\
\- Mistral — efficient open-weight conversational model
