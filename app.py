import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from rag import retrieve_context
from generator import generate_artifact

load_dotenv()
ROOT = Path(__file__).parent
KNOWLEDGE_DIR = ROOT / "knowledge"

st.set_page_config(page_title="AIDevOps Copilot", page_icon="🛠️", layout="wide")
st.title("🛠️ AIDevOps Copilot")
st.caption("Prototype: natural-language DevOps assistance with retrieval-augmented generation.")

with st.sidebar:
    st.header("Project status")
    st.write("Implemented in this starter:")
    st.write("- Natural-language task input")
    st.write("- TF-IDF retrieval from local DevOps notes")
    st.write("- Artifact generation for Jenkins, Docker, or Terraform")
    st.write("- API mode plus a deterministic demo fallback")
    st.warning("Generated configurations are suggestions. Review them before use; this app does not execute commands or deploy infrastructure.")
    api_ready = bool(os.getenv("OPENAI_API_KEY"))
    st.write("LLM API configured:", "✅ Yes" if api_ready else "⚠️ No — demo fallback")

artifact_type = st.selectbox(
    "What do you want to generate?",
    ["Jenkins pipeline (Jenkinsfile)", "Dockerfile", "Terraform (AWS starter)"],
)
task = st.text_area(
    "Describe your DevOps task",
    placeholder="Example: Create a Jenkins pipeline for a Maven Java application that runs tests and builds a Docker image.",
    height=120,
)
project_details = st.text_input(
    "Optional project details",
    placeholder="Example: Java 21, Maven, app entry point target/app.jar",
)

col1, col2 = st.columns([1, 1])
with col1:
    generate_clicked = st.button("Generate artifact", type="primary", use_container_width=True)
with col2:
    st.button("Clear is handled by editing the fields above", disabled=True, use_container_width=True)

if generate_clicked:
    if not task.strip():
        st.error("Enter a task description first.")
        st.stop()

    query = f"{artifact_type}\n{task}\n{project_details}"
    with st.spinner("Retrieving relevant notes and preparing a response..."):
        retrieved = retrieve_context(query, KNOWLEDGE_DIR)
        result, mode = generate_artifact(
            artifact_type=artifact_type,
            task=task,
            project_details=project_details,
            retrieved_context=retrieved,
        )

    st.subheader("Generated output")
    st.caption(f"Generation mode: {mode}")
    st.code(result, language="yaml" if "Terraform" in artifact_type else "groovy" if "Jenkins" in artifact_type else "dockerfile")
    st.download_button(
        "Download generated file",
        data=result,
        file_name=(
            "Jenkinsfile" if "Jenkins" in artifact_type
            else "Dockerfile" if "Dockerfile" in artifact_type
            else "main.tf"
        ),
        mime="text/plain",
    )

    with st.expander("Retrieved knowledge-base context"):
        st.write(retrieved if retrieved else "No relevant local notes found.")
    st.info("Next step: review the output, test it in a safe sample repository, and record any validation errors. This prototype does not run the generated file.")
else:
    st.subheader("Demo workflow")
    st.markdown("1. Choose an artifact type.\n2. Describe the task.\n3. Generate the configuration.\n4. Inspect the retrieved notes and download the output.")
