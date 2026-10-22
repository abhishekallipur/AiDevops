from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def retrieve_context(query: str, knowledge_dir: Path, top_k: int = 3) -> str:
    """Small, transparent local retrieval pipeline using TF-IDF and cosine similarity."""
    documents = []
    for path in sorted(knowledge_dir.glob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if content.strip():
            documents.append((path.name, content))

    if not documents:
        return ""

    corpus = [content for _, content in documents]
    vectorizer = TfidfVectorizer(stop_words="english")
    try:
        matrix = vectorizer.fit_transform(corpus + [query])
    except ValueError:
        return ""

    query_vector = matrix[-1]
    doc_matrix = matrix[:-1]
    scores = cosine_similarity(query_vector, doc_matrix).flatten()
    ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)[:top_k]

    chunks = []
    for index, score in ranked:
        if score <= 0:
            continue
        name, content = documents[index]
        chunks.append(f"Source: {name} (retrieval score: {score:.3f})\n{content[:3500]}")
    return "\n\n---\n\n".join(chunks)
