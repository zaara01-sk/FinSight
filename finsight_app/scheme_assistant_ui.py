"""Single assistant response with visible, backend-controlled citations."""
from services.rag.conversation import chat
from services.rag.language import LANGUAGES, TEXT
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote


@lru_cache(maxsize=1)
def mascot_image():
    svg = (Path(__file__).parent / "assets" / "finny.svg").read_text(encoding="utf-8")
    return "data:image/svg+xml," + quote(svg, safe="")


HELP_STYLE = """
<style>
div.st-key-scheme_help_launcher {
    position: fixed !important; left: auto !important;
    right: max(18px, env(safe-area-inset-right)) !important;
    bottom: max(12px, env(safe-area-inset-bottom)) !important;
    width: 156px !important; min-width: 156px !important;
    max-width: 156px !important; z-index: 100001 !important;
    pointer-events: auto;
}
.st-key-scheme_help_launcher button {
    position: relative; display: flex; flex-direction: column; gap: 0;
    width: 156px !important; min-height: 152px; padding: 20px 8px 7px;
    border: none !important; border-radius: 28px;
    background: transparent !important; color: #173B57 !important;
    box-shadow: none !important; cursor: pointer;
}
.st-key-scheme_help_launcher button::before {
    content: ''; display: block; width: 104px; height: 110px; flex: 0 0 110px;
    background: url('__MASCOT_IMAGE__') center / contain no-repeat;
    filter: drop-shadow(0 5px 7px #173b5725);
    animation: finny-hover 3.8s ease-in-out infinite;
}
.st-key-scheme_help_launcher button::after {
    content: 'Hi · नमस्ते · नमस्कार'; position: absolute; left: 0; top: 0;
    width: 156px; padding: 5px 0; border: 1px solid #b5dbe8;
    border-radius: 14px 14px 14px 4px; background: #ffffff;
    font-size: 11px; font-weight: 600; color: #225671;
    box-shadow: 0 3px 10px #173b5710;
}
.st-key-scheme_help_launcher button p {
    font-size: 12px !important; font-weight: 700; background: #ffffff;
    border: 1px solid #c9e2ee; padding: 3px 12px; border-radius: 20px;
}
.st-key-scheme_help_launcher button:hover::before { filter: drop-shadow(0 5px 10px #259ab64d); }
.st-key-scheme_help_launcher button:focus-visible { outline: 3px solid #087eab !important; outline-offset: 3px; }
@keyframes finny-hover { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
@media (prefers-reduced-motion: reduce) { .st-key-scheme_help_launcher button::before { animation: none; } }
[data-testid="stPopoverBody"]:has(.st-key-scheme_help_content) {
    position: fixed !important; left: auto !important; top: auto !important;
    right: max(18px, env(safe-area-inset-right)) !important;
    bottom: 182px !important; transform: none !important;
    width: min(410px, calc(100vw - 32px));
    max-height: min(620px, calc(100dvh - 255px));
    overflow-y: auto; overscroll-behavior: contain;
    background: var(--background-color, #ffffff);
    border: 1px solid #bdd8e5; border-radius: 18px;
    padding: 20px; box-shadow: 0 12px 42px #163c5133;
    z-index: 100000 !important; pointer-events: auto;
}
.st-key-scheme_help_content h3 { font-size: 1.15rem; }
.st-key-scheme_help_content [data-testid="stChatMessage"] { padding: 12px; }
.st-key-scheme_help_content [data-testid="stTextArea"] textarea {
    padding-bottom: 2.25rem !important; line-height: 1.5;
}
.st-key-scheme_help_content [data-testid="InputInstructions"] {
    display: none !important;
}
/* Raise the portal itself: a child's z-index cannot escape its parent's layer. */
#stFloatingOverlayPortal:has(.st-key-scheme_help_content) { z-index: 100002 !important; }
.st-key-scheme_help_launcher [data-testid="stIconMaterial"] { display: none; }
@media (max-width: 600px), (max-height: 650px) {
    div.st-key-scheme_help_launcher { right: 10px !important; width: 118px !important;
        min-width: 118px !important; max-width: 118px !important; }
    .st-key-scheme_help_launcher button { width: 118px !important; min-height: 104px; padding-top: 0; }
    .st-key-scheme_help_launcher button::before { width: 76px; height: 80px; flex-basis: 80px; }
    .st-key-scheme_help_launcher button::after { display: none; }
    [data-testid="stPopoverBody"]:has(.st-key-scheme_help_content) {
        right: 10px !important; bottom: 132px !important;
        width: calc(100vw - 20px); max-width: 410px; max-height: calc(100dvh - 200px); }
}
</style>
"""


def render_help_assistant(st, business_id):
    """Small fixed launcher; expensive work runs only after an explicit question."""
    st.markdown(HELP_STYLE.replace("__MASCOT_IMAGE__", mascot_image()), unsafe_allow_html=True)
    # Right-edge anchoring keeps the launcher in the main viewport, including
    # when the sidebar is collapsed. The conversation uses a native portal.
    try:
        popover_ctx = st.popover("Ask Finny", key="scheme_help_launcher", type="primary", width=156)
    except TypeError:
        popover_ctx = st.popover("Ask Finny")
    with popover_ctx:
        try:
            container_ctx = st.container(key="scheme_help_content")
        except TypeError:
            container_ctx = st.container()
        with container_ctx:
            render_assistant(st, business_id)


def render_assistant(st, business_id):
    st.subheader("Finny · Your FinSight guide")
    st.caption("Hello! नमस्ते! नमस्कार! Ask about your dashboard, finances or government schemes.")
    with st.expander("Language, profile & privacy"):
        selected = st.selectbox("Language", list(LANGUAGES), key=f"scheme_language_{business_id}")
        st.caption("Eligibility uses the same saved profile and local screening rules as Government Schemes.")
        use_dashboard = st.checkbox("Use dashboard summaries for explanations", value=True,
                                    key=f"scheme_dashboard_share_{business_id}")
        st.caption("Your question, recent chat context, enabled dashboard summaries and official source passages are sent to Groq. Raw transactions, account identifiers and credentials are never sent. Scheme profiles filter locally.")
        st.caption("Scheme rules can change. Confirm final eligibility on the official website. Save your profile under Government Schemes to use it here.")
    key = f"scheme_answer_{business_id}"
    history_key = f"scheme_chat_history_{business_id}"
    try:
        form_ctx = st.form(f"scheme_chat_form_{business_id}", clear_on_submit=True, enter_to_submit=False)
    except TypeError:
        form_ctx = st.form(f"scheme_chat_form_{business_id}", clear_on_submit=True)
    with form_ctx:
        question = st.text_area("Message Finny", max_chars=2000, height=110,
                                 placeholder="Ask in English, हिन्दी or Hinglish…",
                                 key=f"scheme_query_{business_id}")
        try:
            submitted = st.form_submit_button("Ask Finny", icon=":material/send:", width="stretch")
        except TypeError:
            try:
                submitted = st.form_submit_button("Ask Finny", icon=":material/send:", use_container_width=True)
            except TypeError:
                submitted = st.form_submit_button("Ask Finny")
    if submitted:
        if not question.strip():
            st.warning("Enter a question first.")
            st.session_state.pop(key, None)
        else:
            profile = st.session_state.get(f"scheme_profile_{business_id}", {})
            history = st.session_state.get(history_key, [])
            dashboard = dict(st.session_state.get(f"scheme_dashboard_context_{business_id}", {})) if use_dashboard else {}
            dashboard["current_page"] = st.session_state.get("app_page", "Unknown")
            with st.spinner("Finny is thinking…"):
                answer = chat(question, LANGUAGES[selected], profile, history=history, dashboard=dashboard)
                st.session_state[key] = answer
                st.session_state[f"scheme_last_question_{business_id}"] = question
                if answer["status"] != "unavailable":
                    st.session_state[history_key] = (history + [{
                        "question": question, "status": answer["status"], "language": answer["language"],
                        "scheme_ids": [c["scheme_id"] for c in answer["recommendations"]] or [c["scheme_name"] for c in answer.get("screening_results", [])],
                        "clarification": answer["message"] if answer["status"] == "clarification" else "",
                        "answer": answer["message"],
                        "answer_payload": answer,
                    }])[-10:]
    chat_history = st.session_state.get(history_key, [])
    if not chat_history:
        answer = st.session_state.get(key)
        if answer:
            with st.chat_message("user"):
                st.write(st.session_state.get(f"scheme_last_question_{business_id}", ""))
            with st.chat_message("assistant"):
                _render_answer(st, answer)
        else:
            st.caption("Try: Which government scheme am I eligible for? or What documents do I need?")
        return

    for turn in chat_history:
        with st.chat_message("user"):
            st.write(turn["question"])
        with st.chat_message("assistant"):
            if "answer_payload" in turn:
                _render_answer(st, turn["answer_payload"])
            else:
                _render_answer(st, {"language": turn.get("language", "en"), "message": turn.get("answer", "")})

    if st.button("Clear conversation", key=f"clear_chat_{business_id}"):
        st.session_state[history_key] = []
        st.session_state.pop(key, None)
        st.rerun()


def _render_answer(st, answer):
    labels = TEXT[answer["language"]]
    st.info(answer["message"])
    for row in answer.get("screening_results", []):
        with st.expander(row["scheme_name"] + " · " + row["relevance"]):
            st.caption("Local screening result · same rules as Government Schemes")
            if row["missing_information"]:
                st.write("Additional information required: " + ", ".join(row["missing_information"]))
            for reason in row["failed_reasons"]:
                st.write("Not matched: " + reason)
            st.caption("Ask me about this scheme for its official-source explanation. Screening is not a lender approval.")
    for source in answer.get("sources", []):
        st.link_button(source["name"] + " · " + labels["source"], source["url"])
    if answer["status"] == "no_evidence":
        st.link_button("Search official schemes", "https://www.myscheme.gov.in/")
    for card in answer["recommendations"]:
        with st.container(border=True):
            st.subheader(card["scheme_name"])
            st.caption(card["status"])
            for claim in card["claims"]:
                st.markdown(f"**{labels[claim['field']]}**")
                st.text(claim["claim"])
            st.markdown(f"**{labels['missing']}**")
            st.text(labels["review"])
            if card["missing_information"]:
                st.caption("Profile fields: " + ", ".join(card["missing_information"]))
            st.caption("Source verified · Last checked " + card["last_checked_at"])
            st.link_button(labels["source"], card["source_url"])
            with st.expander("View evidence"):
                for claim in card["claims"]:
                    st.text(claim["source_chunk"] + " — " + claim["claim"])
    if answer["language"] != "en" and answer["recommendations"]:
        st.caption("Translated information is provided for convenience. Refer to the official source for authoritative scheme details.")
