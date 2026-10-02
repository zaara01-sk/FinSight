"""One validated answer path, with failure isolation and minimal API disclosure."""
import logging
import time
import re
from .generator import generate, ProviderError
from .config import semantic_enabled
from .language import TEXT, detect_language
from .repository import eligibility, load_records, valid_record
from .retriever import retrieve

LOG = logging.getLogger(__name__)
UNAVAILABLE = "The Scheme Assistant is temporarily unavailable. Your FinSight analytics and reports are unaffected."
PROVIDER_MESSAGES = {
    "missing_key": "Add GROQ_API_KEY to the project's .env file to enable the assistant.",
    "invalid_key": "Groq rejected the API key. Check GROQ_API_KEY in your .env file.",
    "access_denied": "Groq denied this request. Check your account's model permissions and network access.",
    "model_unavailable": "The configured Groq model is unavailable to your account. Update LLM_MODEL in .env to an accessible model.",
    "rate_limit": "Groq's usage limit was reached. Wait a moment and try again, or check your Groq quota.",
    "network_error": "Could not reach Groq. Check your connection and try again.",
    "invalid_response": "Groq returned an incomplete answer. Please try again.",
    "provider_error": "Groq could not complete the request. Please try again shortly.",
}


def validate_answer(output, records, language, profile):
    if not isinstance(output, dict) or not isinstance(output.get("recommendations"), list):
        raise ValueError("Invalid structured answer")
    trusted = {r["scheme_id"]: r for r in records}
    cards, seen = [], set()
    for item in output["recommendations"]:
        if not isinstance(item, dict) or set(item) != {"scheme_id", "evidence_chunk_ids"}:
            raise ValueError("Unexpected generated fields")
        sid = item["scheme_id"]
        if not isinstance(sid, str) or sid not in trusted:
            raise ValueError("Unknown scheme")
        record = trusted[sid]
        ids = item["evidence_chunk_ids"]
        allowed = {sid + ":" + field for field in record["facts"]}
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in allowed for i in ids):
            raise ValueError("Unknown evidence")
        if not valid_record(record):
            raise ValueError("Source failed validation")
        missing, failed = eligibility(record, profile)
        if failed or sid in seen:
            continue
        seen.add(sid)
        claims = [{"claim": record["facts"][i.split(":", 1)[1]].get(language, record["facts"][i.split(":", 1)[1]]["en"]),
                   "field": i.split(":", 1)[1], "source_chunk": i, "source_url": record["official_url"]} for i in ids]
        cards.append({"scheme_id": sid, "scheme_name": record["scheme_name"], "claims": claims,
                      "source_url": record["official_url"], "last_checked_at": record["last_checked_at"],
                      "missing_information": missing, "status": TEXT[language]["status"]})
    return cards


def ask(question, language="auto", profile=None, *, records=None, generator=generate, use_embeddings=None):
    started = time.monotonic()
    lang = detect_language(question, language)
    result = {"language": lang, "message": TEXT[lang]["none"], "recommendations": [], "status": "no_evidence"}
    if not question.strip() or len(question) > 2000:
        return result
    normalized = question.casefold().strip(" .!?।")
    if re.fullmatch(r"(?:hello|hi|hey|namaste|namaskar|नमस्ते|नमस्कार|हैलो)(?:\s+finny)?", normalized):
        message = {
            "en": "Hi, I'm Finny! I can help you explore government schemes, eligibility and official sources. Tell me about your business, or ask about PMEGP, MUDRA or CGTMSE.",
            "hi": "नमस्ते! मैं Finny हूँ। मैं सरकारी योजनाओं, पात्रता और आधिकारिक स्रोतों में मदद कर सकता हूँ। अपने व्यवसाय के बारे में बताइए या PMEGP, MUDRA या CGTMSE के बारे में पूछिए।",
            "mr": "नमस्कार! मी Finny आहे. सरकारी योजना, पात्रता आणि अधिकृत स्रोत शोधण्यात मदत करू शकतो. तुमच्या व्यवसायाबद्दल सांगा किंवा PMEGP, MUDRA किंवा CGTMSE बद्दल विचारा.",
        }[lang]
        return dict(result, status="conversation", message=message)
    documents_question = any(word in normalized for word in (
        "document", "paperwork", "checklist", "dastavez", "kagaz", "दस्तावेज", "कागदपत्र"))
    try:
        if use_embeddings is None:
            use_embeddings = semantic_enabled()
        catalog = load_records() if records is None else [r for r in records if valid_record(r)]
        if documents_question:
            named = [r for r in catalog if any(a.casefold() in normalized for a in r["aliases"])]
            sids = [r["scheme_id"] for r in named]
            target_sid = sids[0] if sids else "general"
            
            doc_checklists = {
                "pmegp": {
                    "en": "Required documents for PMEGP (Prime Minister's Employment Generation Programme):\n\n"
                          "1. Identity & Address Proof: Aadhaar Card, PAN Card\n"
                          "2. Business Registration: Udyam MSME Registration Certificate\n"
                          "3. Project Report (DPR): Detailed project report showing capital expenditure, working capital, and break-even\n"
                          "4. Educational Qualification: 8th pass certificate (mandatory for projects > ₹10 Lakh in manufacturing or > ₹5 Lakh in service)\n"
                          "5. Category Certificate: SC/ST/OBC/Minority/Women/Ex-servicemen certificate (to claim 25%-35% subsidy)\n"
                          "6. EDP Training: Entrepreneurship Development Programme certificate (or undertaking)\n"
                          "7. Financials & Photos: 6 months bank statement and passport-size photographs.\n\n"
                          "Refer to the official portal below for current guidelines:",
                    "hi": "PMEGP (प्रधानमंत्री रोजगार सृजन कार्यक्रम) के लिए आवश्यक मुख्य दस्तावेज़:\n\n"
                          "1. पहचान एवं पता प्रमाण: आधार कार्ड, पैन कार्ड\n"
                          "2. व्यवसाय प्रमाण: उद्यम (MSME) पंजीकरण प्रमाणपत्र\n"
                          "3. प्रोजेक्ट रिपोर्ट (DPR): विस्तृत परियोजना रिपोर्ट (पूंजीगत खर्च, कार्यशील पूंजी और अनुमानित लाभ)\n"
                          "4. शैक्षणिक योग्यता: 8वीं पास प्रमाणपत्र (विनिर्माण में ₹10 लाख और सेवा क्षेत्र में ₹5 लाख से अधिक की परियोजना के लिए अनिवार्य)\n"
                          "5. विशेष श्रेणी प्रमाणपत्र: SC/ST/OBC/महिला/दिव्यांग प्रमाणपत्र (25% से 35% तक सब्सिडी पाने के लिए)\n"
                          "6. EDP प्रशिक्षण: उद्यमशीलता विकास प्रशिक्षण प्रमाणपत्र\n"
                          "7. बैंक खाता एवं फोटो: पिछले 6 महीने का बैंक स्टेटमेंट और पासपोर्ट साइज फोटो।\n\n"
                          "आधिकारिक दिशा-निर्देशों के लिए नीचे दिए गए पोर्टल को देखें:",
                    "mr": "PMEGP (पंतप्रधान रोजगार निर्मिती कार्यक्रम) साठी आवश्यक कागदपत्रे:\n\n"
                          "1. ओळख व पत्ता पुरावा: आधार कार्ड, पॅन कार्ड\n"
                          "2. व्यवसाय नोंदणी: उद्यम (MSME) नोंदणी प्रमाणपत्र\n"
                          "3. सविस्तर प्रकल्प अहवाल (DPR): भांडवली खर्च, खेळते भांडवल आणि नफ्याचा तपशील\n"
                          "4. शैक्षणिक पात्रता: 8 वी उत्तीर्ण प्रमाणपत्र (उत्पादनात ₹10 लाख व सेवा क्षेत्रात ₹5 लाखांपेक्षा जास्त प्रकल्पांसाठी अनिवार्य)\n"
                          "5. विशेष वर्ग प्रमाणपत्र: SC/ST/OBC/महिला प्रमाणपत्र (25% ते 35% अनुदान सवलतीसाठी)\n"
                          "6. EDP प्रशिक्षण प्रमाणपत्र: उद्योजकता विकास प्रशिक्षण प्रमाणपत्र\n"
                          "7. बँक खात्याचा पुरावा: मागील 6 महिन्यांचे बँक स्टेटमेंट आणि पासपोर्ट आकाराचे फोटो.\n\n"
                          "सध्याच्या अधिकृत मार्गदर्शक तत्त्वांसाठी खालील लिंक तपासा:"
                },
                "mudra": {
                    "en": "Required documents for MUDRA Loan (Shishu, Kishore & Tarun):\n\n"
                          "1. Identity & Address Proof: Aadhaar Card, PAN Card, Voter ID, or Driving License\n"
                          "2. Business Proof: Udyam MSME Registration, Shop Act License, or Trade License\n"
                          "3. Asset Purchase Quotation: Quotations/invoices of machinery, equipment, or items to be purchased\n"
                          "4. Bank Statement: Statement of the existing bank account for the last 6 months\n"
                          "5. Financial Proof (for Kishore/Tarun > ₹50,000): Past 1-2 years ITR and Balance Sheet (if existing business)\n"
                          "6. Passport Photographs: 2 passport-size photos of applicant/promoters\n\n"
                          "Note: MUDRA loans are 100% collateral-free. Refer to the official source below:",
                    "hi": "MUDRA ऋण (शिशु, किशोर एवं तरुण) के लिए आवश्यक मुख्य दस्तावेज़:\n\n"
                          "1. पहचान एवं पता प्रमाण: आधार कार्ड, पैन कार्ड, वोटर आईडी\n"
                          "2. व्यवसाय प्रमाण: उद्यम पंजीकरण प्रमाणपत्र, शॉप एक्ट लाइसेंस या ट्रेड लाइसेंस\n"
                          "3. कोटेशन: खरीदी जाने वाली मशीनरी, उपकरण या माल का कोटेशन/बिल\n"
                          "4. बैंक विवरण: पिछले 6 महीनों का बैंक खाता विवरण (स्टेटमेंट)\n"
                          "5. वित्तीय विवरण (किशोर/तरुण ऋण हेतु): पिछले 1-2 साल का ITR या बैलेंस शीट (यदि व्यवसाय पहले से चालू हो)\n"
                          "6. फोटो: आवेदक के 2 पासपोर्ट साइज फोटो\n\n"
                          "विशेष नोट: मुद्रा ऋण के लिए किसी तारण (Collateral/Security) की आवश्यकता नहीं होती। नीचे आधिकारिक स्रोत देखें:",
                    "mr": "MUDRA कर्ज (शिशू, किशोर आणि तरुण) साठी आवश्यक मुख्य कागदपत्रे:\n\n"
                          "1. ओळख व पत्ता पुरावा: आधार कार्ड, पॅन कार्ड किंवा मतदार ओळखपत्र\n"
                          "2. व्यवसाय पुरावा: उद्यम नोंदणी प्रमाणपत्र, शॉप ॲक्ट लायसन्स किंवा व्यवसाय परवाना\n"
                          "3. कोटेशन: खरेदी करावयाच्या यंत्रसामग्री किंवा मालाचे कोटेशन\n"
                          "4. बँक स्टेटमेंट: मागील 6 महिन्यांचे बँक खाते विवरण\n"
                          "5. आर्थिक कागदपत्रे: मागील 1-2 वर्षांचे आयटीआर आणि ताळेबंद (चालू व्यवसायासाठी)\n"
                          "6. फोटो: अर्जदाराचे 2 पासपोर्ट आकाराचे फोटो\n\n"
                          "टीप: मुद्रा कर्जासाठी कोणत्याही तारण किंवा हमीची आवश्यकता नसते. खालील अधिकृत स्रोत तपासा:"
                },
                "cgtmse": {
                    "en": "Required documents for CGTMSE Collateral-Free Credit Guarantee Scheme:\n\n"
                          "1. Promoter KYC: Aadhaar Card and PAN Card of business owner/partners/directors\n"
                          "2. Business Legal Proof: Udyam Registration, Partnership Deed / Certificate of Incorporation, GST Registration\n"
                          "3. Detailed Project Report (DPR): Business viability model, project cost, promoter contribution, and 3-5 year financial projections\n"
                          "4. Financial Statements: Last 2-3 years audited Balance Sheet, P&L account, and ITR (for existing units)\n"
                          "5. Banking Records: Past 12 months bank statement of all existing accounts\n"
                          "6. Asset Quotations: Invoices/quotations for plant, machinery, or equipment to be financed\n\n"
                          "Note: CGTMSE guarantees loans up to ₹5 Crore without third-party collateral. Refer to official portal below:",
                    "hi": "CGTMSE (क्रेडिट गारंटी फंड ट्रस्ट) संपार्श्विक-मुक्त ऋण योजना के लिए आवश्यक दस्तावेज़:\n\n"
                          "1. आवेदक/प्रमोटर KYC: आधार कार्ड, पैन कार्ड\n"
                          "2. कानूनी व्यवसाय प्रमाण: उद्यम पंजीकरण, साझेदारी विलेख / निगमन प्रमाणपत्र, GST प्रमाण\n"
                          "3. विस्तृत प्रोजेक्ट रिपोर्ट (DPR): 3-5 वर्षों के वित्तीय अनुमान, परियोजना लागत और प्रमोटर योगदान का विवरण\n"
                          "4. वित्तीय विवरण: पिछले 2-3 वर्षों की ऑडिटेड बैलेंस शीट, लाभ-हानि खाता और आईटीआर\n"
                          "5. बैंक स्टेटमेंट: पिछले 12 महीनों का चालू बैंक खाता विवरण\n"
                          "6. कोटेशन: खरीदी जाने वाली मशीनरी और उपकरणों के कोटेशन\n\n"
                          "विशेष नोट: इस योजना के तहत ₹5 करोड़ तक का ऋण बिना किसी तीसरे पक्ष की गारंटी या बंधक के मिलता है। नीचे आधिकारिक स्रोत देखें:",
                    "mr": "CGTMSE विनातारण हमी कर्ज योजनेसाठी आवश्यक कागदपत्रे:\n\n"
                          "1. प्रमोटर केवायसी (KYC): आधार कार्ड, पॅन कार्ड\n"
                          "2. व्यावसायिक कायदेशीर पुरावा: उद्यम नोंदणी, भागीदारी करार / कंपनी नोंदणी, GST प्रमाणपत्र\n"
                          "3. सविस्तर प्रकल्प अहवाल (DPR): व्यवसाय व्यवहार्यता, 3 ते 5 वर्षांचे आर्थिक अंदाज\n"
                          "4. आर्थिक विवरणे: मागील 2-3 वर्षांचे ऑडिट केलेले ताळेबंद, नफा-तोटा पत्रक आणि आयटीआर\n"
                          "5. बँक स्टेटमेंट: मागील 12 महिन्यांचे बँक स्टेटमेंट\n"
                          "6. कोटेशन्स: यंत्रसामग्री व उपकरणांचे अधिकृत कोटेशन\n"
                          "टीप: या योजनेअंतर्गत ₹5 कोटींपर्यंतचे कर्ज कोणत्याही वैयक्तिक तारणाशिवाय उपलब्ध होते. खालील अधिकृत स्रोत तपासा:"
                },
                "general": {
                    "en": "General documents required for MSME government schemes (PMEGP, MUDRA, CGTMSE):\n\n"
                          "1. KYC Proof: Aadhaar Card, PAN Card, Voter ID\n"
                          "2. Business Proof: Udyam MSME Registration Certificate, Shop Act / Trade License\n"
                          "3. Banking Records: Past 6 to 12 months Bank Account Statements\n"
                          "4. Business Plan: Detailed Project Report (DPR) or quotation for machinery/goods\n"
                          "5. Financials: Previous 1-2 years ITR and Balance Sheet (if existing business)\n"
                          "6. Photographs: 2 passport-size photos\n\n"
                          "Which specific scheme are you planning to apply for? Tell me (PMEGP, MUDRA, or CGTMSE) for exact requirements!",
                    "hi": "MSME सरकारी योजनाओं (PMEGP, MUDRA, CGTMSE) के लिए सामान्य आवश्यक दस्तावेज़:\n\n"
                          "1. पहचान एवं पता प्रमाण (KYC): आधार कार्ड, पैन कार्ड, वोटर आईडी\n"
                          "2. व्यवसाय प्रमाण: उद्यम MSME पंजीकरण, शॉप एक्ट / ट्रेड लाइसेंस\n"
                          "3. बैंक रिकॉर्ड: पिछले 6 से 12 महीनों का बैंक स्टेटमेंट\n"
                          "4. बिजनेस प्लान: विस्तृत प्रोजेक्ट रिपोर्ट (DPR) या मशीनरी/माल का कोटेशन\n"
                          "5. वित्तीय रिकॉर्ड: पिछले 1-2 वर्षों का आईटीआर और बैलेंस शीट (यदि व्यवसाय चालू है)\n"
                          "6. फोटो: 2 पासपोर्ट साइज फोटो\n\n"
                          "आप किस विशेष योजना (PMEGP, MUDRA या CGTMSE) के लिए आवेदन करना चाहते हैं? मुझे बताएं ताकि मैं सटीक सूची दे सकूँ!",
                    "mr": "MSME सरकारी योजनांसाठी (PMEGP, MUDRA, CGTMSE) सामान्यतः आवश्यक कागदपत्रे:\n\n"
                          "1. ओळख व पत्ता पुरावा (KYC): आधार कार्ड, पॅन कार्ड\n"
                          "2. व्यवसाय पुरावा: उद्यम MSME नोंदणी प्रमाणपत्र, शॉप ॲक्ट\n"
                          "3. बँक पुरावा: मागील 6 ते 12 महिन्यांचे बँक खाते विवरण\n"
                          "4. व्यवसाय योजना: सविस्तर प्रकल्प अहवाल (DPR) किंवा कोटेशन\n"
                          "5. आर्थिक पुरावा: मागील 1-2 वर्षांचे आयटीआर आणि ताळेबंद\n"
                          "6. फोटो: 2 पासपोर्ट आकाराचे फोटो\n\n"
                          "तुम्ही कोणत्या विशिष्ट योजनेसाठी (PMEGP, MUDRA की CGTMSE) अर्ज करू इच्छिता? मला सांगा जेणेकरून मी अचूक यादी देऊ शकेन!"
                }
            }
            checklist_entry = doc_checklists.get(target_sid, doc_checklists["general"])
            message = checklist_entry.get(lang, checklist_entry["en"])
            
            if not named:
                sources = [{"name": r["scheme_name"], "url": r["official_url"]} for r in catalog]
                return dict(result, status="clarification", message=message, followup_question=question, sources=sources)
            
            return dict(result, status="source_guidance", message=message,
                        sources=[{"name": r["scheme_name"], "url": r["official_url"]} for r in named])
        candidates = retrieve(question, catalog, use_embeddings)
        candidates = [r for r in candidates if not eligibility(r, profile or {})[1]]
        if not candidates:
            return result
        output = generator(question, candidates, lang)
        cards = validate_answer(output, candidates, lang, profile or {})
        if cards:
            result.update(message=TEXT[lang]["intro"], recommendations=cards, status="ok")
        LOG.info("rag language=%s sources=%s cards=%d duration=%.3f", lang,
                 [r["scheme_id"] for r in candidates], len(cards), time.monotonic() - started)
    except ProviderError as error:
        LOG.warning("rag provider_failure=%s http_status=%s", error.code, error.status)
        result.update(message=PROVIDER_MESSAGES[error.code], status="unavailable", error_code=error.code)
    except Exception as error:
        LOG.warning("rag fallback=%s", type(error).__name__)
        result.update(message=UNAVAILABLE, status="unavailable")
    return result
