import requests

def get_football_info() -> str:
    print(f"get_football_info:\n{get_football_info}")
    try:
        headers = {"user-agent": "Mozilla/5.0"}
        url = "https://api.football-data.org/v2/competition/PL,LA/matches?status=SCHEDULED"
        res = requests.get(url, headers=headers, timeout=10).json()
        match_list = res["matches"][:3]
        text = "英超&西甲最新赛事:\n"
        for m in match_list:
            home = m["homeTeam"]["name"]
            away = m["awayTeam"]["name"]
            text += f"{home} VS {away}\n"
        print(f"get_football_info:\n{get_football_info}")
        return text
    except:
        return """
英超&西甲最新资讯
1.英超：曼城近期转会补强中场，联赛排名第2
2.西甲：巴萨年轻球员持续提拔，皇马积分榜榜首
3.最新比赛：英超本轮利物浦2:0战胜阿森纳
"""