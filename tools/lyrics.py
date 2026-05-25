import requests

def get_lyrics(song_name: str) -> str:
    try:
        url = f"https://api.lrc.cx/api.php?lyric={song_name}"
        data = requests.get(url, timeout=8).json()
        return f"《{song_name}》歌词:\n{data['lyric'][:500]}"
    except:
        return f"《{song_name}》歌词未找到"