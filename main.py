import streamlit as st

from src.helper import (
    ask_gemini,
    build_job_keyword_prompt,
    build_resume_analysis_prompt,
    extract_text_from_pdf,
    is_gemini_configured,
)
from src.job_api import fetch_linkedin_jobs


st.set_page_config(page_title="AI Job Recommender", layout="wide")

st.title("AI Job Recommender")
st.markdown(
    "Upload your resume and get AI-powered insights including summary, skill gaps, roadmap, "
    "and LinkedIn job recommendations."
)

with st.sidebar:
    st.header("Preferences")
    location = st.text_input("Location", value="Nepal")
    preferred_domain = st.text_input("Preferred field/domain", value="")

if not is_gemini_configured():
    st.error("GEMINI_API_KEY is missing. Add it to the .env file, then restart Streamlit.")
    st.code('GEMINI_API_KEY="your_gemini_api_key_here"', language="text")
    st.stop()

uploaded_file = st.file_uploader("Upload Resume (PDF)", type=["pdf"])

if uploaded_file:
    with st.spinner("Extracting resume text..."):
        resume_text = extract_text_from_pdf(uploaded_file)

    if len(resume_text) < 80:
        st.warning("The PDF text looks empty or unclear. Please upload a clearer resume PDF.")
        st.stop()

    try:
        with st.spinner("Analyzing resume and generating career guidance..."):
            analysis = ask_gemini(
                build_resume_analysis_prompt(
                    resume_text,
                    location=location,
                    domain=preferred_domain,
                ),
                max_tokens=1800,
            )
    except Exception as error:
        st.error(str(error))
        st.stop()

    st.markdown("---")
    st.header("Career Coach Analysis")
    st.markdown(analysis)
    st.success("Analysis completed successfully!")

    if st.button("Get LinkedIn Job Recommendations"):
        try:
            with st.spinner("Generating job search keywords..."):
                keywords = ask_gemini(
                    build_job_keyword_prompt(analysis, resume_text),
                    max_tokens=120,
                )

            search_keywords = keywords.replace("\n", " ").strip()
            st.success(f"Search keywords: {search_keywords}")

            with st.spinner("Fetching LinkedIn jobs..."):
                linkedin_jobs = fetch_linkedin_jobs(search_keywords, location=location, rows=60)
        except Exception as error:
            st.error(str(error))
            linkedin_jobs = []

        st.markdown("---")
        st.header("LinkedIn Jobs")

        if linkedin_jobs:
            for job in linkedin_jobs:
                st.markdown(f"### {job.get('title', 'N/A')}")
                st.markdown(f"**Company:** {job.get('company', 'N/A')}")
                st.markdown(f"**Location:** {job.get('location', 'N/A')}")
                st.markdown(f"[View Job]({job.get('link', '#')})")
                st.markdown("---")
        else:
            st.warning("No LinkedIn jobs found.")
