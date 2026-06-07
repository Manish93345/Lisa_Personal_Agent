"""
LISA — Web Intelligence Module
================================
Weather, News, Smart Search, General Knowledge — sab yahan hai.
Free APIs use karti hai — koi extra API key nahi chahiye.

Return format: WEB_RESULT|type|data
Agent.py is format ko parse karke natural Hinglish mein user ko batata hai.
"""

import urllib.request
import urllib.parse
import json
import xml.etree.ElementTree as ET
from config.settings import DEFAULT_CITY, WEB_SEARCH_TIMEOUT


# ══════════════════════════════════════════════════════════════════════
#  PUBLIC — Router isko call karta hai
# ══════════════════════════════════════════════════════════════════════

def web_search(query: str = "", search_type: str = "search", city: str = "") -> tuple[bool, str]:
    """
    Web Intelligence entry point — router se call hota hai.
    
    Args:
        query       : user ka actual question/topic
        search_type : "weather" | "news" | "search" | "knowledge"
        city        : city name (weather ke liye, blank = default)
    
    Returns:
        (success, "WEB_RESULT|type|data") or (False, "error msg")
    """
    try:
        if search_type == "weather":
            return _get_weather(city or DEFAULT_CITY)
        elif search_type == "news":
            return _get_news(query)
        elif search_type == "knowledge":
            return _get_knowledge(query)
        else:  # "search" — default
            return _smart_search(query)
    except Exception as e:
        print(f"[Web] Error: {e}")
        return False, f"web search mein error aa gaya: {e}"


# ══════════════════════════════════════════════════════════════════════
#  WEATHER — wttr.in (free, no API key)
# ══════════════════════════════════════════════════════════════════════

def _get_weather(city: str) -> tuple[bool, str]:
    """
    wttr.in se live weather fetch karo.
    Free API — no key needed, JSON format.
    """
    try:
        encoded_city = urllib.parse.quote(city)
        url = f"https://wttr.in/{encoded_city}?format=j1"
        
        req = urllib.request.Request(url, headers={"User-Agent": "Lisa-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=WEB_SEARCH_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
        
        current = data.get("current_condition", [{}])[0]
        
        temp_c     = current.get("temp_C", "?")
        feels_like = current.get("FeelsLikeC", "?")
        humidity   = current.get("humidity", "?")
        wind_kmph  = current.get("windspeedKmph", "?")
        condition  = current.get("weatherDesc", [{}])[0].get("value", "?")
        uv_index   = current.get("uvIndex", "?")
        
        # Today's forecast for min/max
        today_forecast = data.get("weather", [{}])[0]
        max_temp = today_forecast.get("maxtempC", "?")
        min_temp = today_forecast.get("mintempC", "?")
        
        # Tomorrow's forecast
        tomorrow = data.get("weather", [{}, {}])
        tomorrow_data = ""
        if len(tomorrow) > 1:
            tmrw = tomorrow[1]
            tmrw_max = tmrw.get("maxtempC", "?")
            tmrw_min = tmrw.get("mintempC", "?")
            # Get hourly for condition
            tmrw_hours = tmrw.get("hourly", [{}])
            tmrw_condition = tmrw_hours[len(tmrw_hours)//2].get("weatherDesc", [{}])[0].get("value", "?") if tmrw_hours else "?"
            tomorrow_data = f";;tomorrow_max:{tmrw_max};;tomorrow_min:{tmrw_min};;tomorrow_condition:{tmrw_condition}"
        
        result = (
            f"city:{city};;temp:{temp_c};;feels_like:{feels_like}"
            f";;condition:{condition};;humidity:{humidity}"
            f";;wind:{wind_kmph};;uv:{uv_index}"
            f";;max:{max_temp};;min:{min_temp}{tomorrow_data}"
        )
        
        return True, f"WEB_RESULT|weather|{result}"
    
    except urllib.error.URLError as e:
        print(f"[Weather] Network error: {e}")
        return False, "internet connection check karo — weather fetch nahi hua"
    except Exception as e:
        print(f"[Weather] Error: {e}")
        return False, f"weather nahi mil rha: {e}"


# ══════════════════════════════════════════════════════════════════════
#  NEWS — Google News RSS (free, no API key)
# ══════════════════════════════════════════════════════════════════════

# Category mapping for Google News RSS
NEWS_CATEGORIES = {
    "top":           "",
    "top news":      "",
    "general":       "",
    "technology":    "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB",
    "tech":          "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB",
    "sports":        "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pKVGlnQVAB",
    "sport":         "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pKVGlnQVAB",
    "entertainment": "CAAqJggKIiBDQkFTRWdvSUwyMHZNREpxYW5RU0FtVnVHZ0pKVGlnQVAB",
    "business":      "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pKVGlnQVAB",
    "science":       "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtVnVHZ0pKVGlnQVAB",
    "health":        "CAAqIQgKIhtDQkFTRGdvSUwyMHZNR3QwTlRFU0FtVnVLQUFQAQ",
}


def _get_news(query: str) -> tuple[bool, str]:
    """
    Google News RSS se headlines fetch karo.
    Free — no API key needed. Top 5-6 headlines.
    """
    try:
        # Determine category
        q_lower = query.lower().strip()
        category_token = ""
        
        for cat_name, token in NEWS_CATEGORIES.items():
            if cat_name in q_lower:
                category_token = token
                break
        
        # Build RSS URL
        if category_token:
            url = f"https://news.google.com/rss/topics/{category_token}?hl=en-IN&gl=IN&ceid=IN:en"
        else:
            url = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
        
        req = urllib.request.Request(url, headers={"User-Agent": "Lisa-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=WEB_SEARCH_TIMEOUT) as response:
            xml_data = response.read().decode("utf-8")
        
        root = ET.fromstring(xml_data)
        channel = root.find("channel")
        
        if channel is None:
            return False, "news feed parse nahi hua"
        
        headlines = []
        items = channel.findall("item")
        
        for item in items[:6]:  # Top 6 headlines
            title = item.find("title")
            source = item.find("source")
            pub_date = item.find("pubDate")
            
            title_text  = title.text if title is not None else "?"
            source_text = source.text if source is not None else ""
            
            # Clean up title — Google News appends " - Source" to title
            if " - " in title_text and source_text:
                title_text = title_text.rsplit(" - ", 1)[0].strip()
            
            entry = f"{title_text}"
            if source_text:
                entry += f" ({source_text})"
            headlines.append(entry)
        
        if not headlines:
            return False, "koi news nahi mili abhi"
        
        # Determine displayed category name
        cat_display = "Top"
        for cat_name in NEWS_CATEGORIES:
            if cat_name in q_lower and cat_name not in ("top", "top news", "general"):
                cat_display = cat_name.capitalize()
                break
        
        news_data = ";;".join(headlines)
        return True, f"WEB_RESULT|news|category:{cat_display};;count:{len(headlines)};;{news_data}"
    
    except urllib.error.URLError as e:
        print(f"[News] Network error: {e}")
        return False, "internet check karo — news fetch nahi hua"
    except Exception as e:
        print(f"[News] Error: {e}")
        return False, f"news nahi mili: {e}"


# ══════════════════════════════════════════════════════════════════════
#  SMART SEARCH — DuckDuckGo Instant Answer API (free)
# ══════════════════════════════════════════════════════════════════════

def _smart_search(query: str) -> tuple[bool, str]:
    """
    DuckDuckGo Instant Answer API — factual questions ke liye.
    Free, no API key. Agar instant answer nahi mila toh LLM fallback.
    """
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
        
        req = urllib.request.Request(url, headers={"User-Agent": "Lisa-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=WEB_SEARCH_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
        
        # Check for instant answer
        abstract = data.get("AbstractText", "").strip()
        answer   = data.get("Answer", "").strip()
        heading  = data.get("Heading", "").strip()
        
        # Direct answer (e.g., calculations, conversions)
        if answer:
            return True, f"WEB_RESULT|search|answer:{answer};;source:DuckDuckGo"
        
        # Abstract (e.g., Wikipedia summaries)
        if abstract:
            # Truncate if too long (keep first 500 chars)
            if len(abstract) > 500:
                abstract = abstract[:497] + "..."
            source = data.get("AbstractSource", "Web")
            return True, f"WEB_RESULT|search|answer:{abstract};;source:{source};;heading:{heading}"
        
        # Related topics (when no direct answer)
        related = data.get("RelatedTopics", [])
        if related:
            snippets = []
            for topic in related[:3]:
                text = topic.get("Text", "")
                if text:
                    snippets.append(text[:200])
            
            if snippets:
                combined = ";;".join(snippets)
                return True, f"WEB_RESULT|search|answer:{combined};;source:DuckDuckGo;;heading:{heading}"
        
        # DuckDuckGo ke paas answer nahi — LLM fallback
        return _get_knowledge(query)
    
    except urllib.error.URLError:
        # Network issue — try LLM fallback (doesn't need internet for knowledge)
        return _get_knowledge(query)
    except Exception as e:
        print(f"[Search] Error: {e}")
        return _get_knowledge(query)


# ══════════════════════════════════════════════════════════════════════
#  KNOWLEDGE — LLM-powered answers (existing Groq/Gemini)
# ══════════════════════════════════════════════════════════════════════

KNOWLEDGE_SYSTEM_PROMPT = """Tum ek knowledge assistant ho. User ka question answer karo:
- Factual aur accurate answer do
- Short aur concise raho (max 3-4 lines)
- Hinglish mein answer do (Roman script, NEVER Devanagari)
- Agar tumhe nahi pata toh honestly bol do "ye mujhe nahi pata"
- Numbers, dates, facts — accurate hone chahiye
- Simple language use karo"""


def _get_knowledge(query: str) -> tuple[bool, str]:
    """
    LLM se direct answer — jab web search mein answer nahi mila
    ya question general knowledge type ka hai.
    Uses existing centralized LLM client.
    """
    try:
        from core.llm_client import call_llm_simple
        
        answer = call_llm_simple(
            system_prompt=KNOWLEDGE_SYSTEM_PROMPT,
            user_message=query,
            temperature=0.3,
            max_tokens=300,
        )
        
        if answer and not answer.startswith("Yaar abhi kuch technical"):
            return True, f"WEB_RESULT|knowledge|answer:{answer};;source:Lisa AI"
        else:
            return False, "abhi answer nahi de paa rhi — thoda baad mein try karo"
    
    except Exception as e:
        print(f"[Knowledge] Error: {e}")
        return False, f"knowledge fetch mein error: {e}"
