"""AI conversation understanding followed by citation-validated scheme retrieval."""
from .assistant import ask, PROVIDER_MESSAGES, UNAVAILABLE
from .generator import complete_json, ProviderError
from .language import detect_language, TEXT
from .dashboard_context import GUIDE
from .screening import answer_scheme

SYSTEM = """You are Finny, FinSight's friendly multilingual AI assistant for MSMEs.
Understand English, Hindi, Marathi and Romanized Hindi/Hinglish (e.g., kaunse, konse, chahiye, chaiye, dastavez, kagaz, kya lagega).
Users may switch languages freely. Always respond in the language of the user's current message.

Return JSON with exactly these fields:
{"intent":"search|chat|clarify","query":"standalone English retrieval question",
 "language":"en|hi|mr","message":"helpful conversational reply"}.

Guidelines:
1. Use "search" ONLY for questions about government scheme ELIGIBILITY or QUALIFICATION:
   e.g. "What schemes am I eligible for?", "Which government schemes can I apply for?", "Am I eligible for Mudra loan/PMEGP?", "Which schemes match my business?".
   For "search", translate to a standalone English query (e.g. "Which government schemes am I eligible for?") and keep "message" empty.

2. Use "chat" for ALL other questions:
   - DOCUMENT QUESTIONS: e.g. "What documents do I specifically need?", "What documents are required for Mudra loan?", "dastavez kya lagenge?". Provide a comprehensive, accurate checklist of required documents (Identity Proof like Aadhaar/PAN, Address Proof, Business Proof/Udyam Registration, Bank Statements for last 6 months, Project Report, Photos) with clean bullet points in the user's language.
   - FOLLOW-UP CONTEXT: If the user replies with just a scheme name (e.g. "PMEGP" or "Mudra") and the recent history was about documents or applying, you MUST use "chat" intent and provide the relevant document checklist or application steps based on the history. DO NOT use "search" intent.
   - APPLICATION STEPS: How and where to apply.
   - DASHBOARD QUESTIONS: Explain anomalies, trends, charts, cash flow, income, expenses, health score, and recommendations using supplied dashboard_summary.
   - GENERAL CONVERSATION & ADVICE: Business guidance, greetings, and definitions.

3. Use "clarify" only for ambiguous requests.
"""


def chat(question, language="auto", profile=None, *, history=None, dashboard=None, planner=complete_json, answerer=answer_scheme):
    lang = detect_language(question, language)
    if language == "auto" and history and question.strip().casefold() in {"mudra", "pmegp", "cgtmse", "pmmy"}:
        lang = history[-1].get("language", lang)
    base = {"language": lang, "message": TEXT[lang]["none"], "recommendations": [], "status": "no_evidence"}
    if not question.strip() or len(question) > 2000:
        return base
    recent = [{"question": str(t.get("question", ""))[:2000],
               "scheme_ids": list(t.get("scheme_ids", []))[:4],
               "status": t.get("status", ""), "language": t.get("language", "en"),
               "answer": str(t.get("answer", ""))[:1500],
               "clarification": str(t.get("clarification", ""))[:500]}
              for t in (history or [])[-6:]]
    try:
        request = {"question": question, "response_language": lang,
                   "recent_conversation": recent, "dashboard_guide": GUIDE,
                   "dashboard_summary": dashboard or {}}
        plan = planner(SYSTEM, request)
        if isinstance(plan, dict) and plan.get("language") in TEXT and plan["language"] != lang:
            plan = planner(SYSTEM + f"\nCORRECTION: Respond in {lang}; ignore the history's language.", request)
        if (not isinstance(plan, dict) or plan.get("intent") not in {"search", "chat", "clarify"}
                or (plan.get("language") and plan.get("language") not in TEXT)
                or not isinstance(plan.get("query"), str) or len(plan["query"]) > 2000
                or not isinstance(plan.get("message"), str) or len(plan["message"]) > 6000):
            raise ProviderError("invalid_response")
        if plan.get("language") and plan["language"] != lang:
            plan["language"] = lang

        if plan["intent"] == "search":
            if not plan["query"].strip():
                raise ProviderError("invalid_response")
            return answerer(plan["query"], lang, profile)

        message = plan["message"].strip()
        if not message or "http" in message.casefold():
            raise ProviderError("invalid_response")
        return dict(base, language=lang, message=message,
                    status="clarification" if plan["intent"] == "clarify" else "conversation")
    except ProviderError as error:
        return dict(base, message=PROVIDER_MESSAGES.get(error.code, UNAVAILABLE), status="unavailable", error_code=error.code)
    except Exception:
        return dict(base, message=UNAVAILABLE, status="unavailable")
