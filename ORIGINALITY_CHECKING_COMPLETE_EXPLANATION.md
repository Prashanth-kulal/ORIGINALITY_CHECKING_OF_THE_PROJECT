# Complete Code Analysis: Originality & Novelty Checking System

> **Document Status:** Verified against the actual codebase of the project (`backend/app.py`, `frontend/team-dasboard.html`, and `frontend/faculty-dashboard.html`).  
> **Rule Followed:** No assumptions, no guessing, no modifications to any existing project file. Every detail is sourced directly from the project's source code.

---

## 1. What Input is Given?

### What the Student Enters on the Frontend
In the student portal ([`frontend/team-dasboard.html`](file:///c:/Users/prashanth/Desktop/student_project_mgmt/frontend/team-dasboard.html#L424-L429)), the user interface presents a form titled **"📂 Submit Project Idea"** with exactly two input fields:
1. **`projectTitle`** (`<input type="text" id="projectTitle" placeholder="Project Title">`)
2. **`projectAbstract`** (`<textarea rows="4" id="projectAbstract" placeholder="Enter project abstract..."></textarea>`)

When the student clicks the **"Submit & Check Originality"** button, the JavaScript function [`submitProject()`](file:///c:/Users/prashanth/Desktop/student_project_mgmt/frontend/team-dasboard.html#L955-L968) executes:
```javascript
const title = document.getElementById("projectTitle").value.trim();
const abstract = document.getElementById("projectAbstract").value.trim();

// Sent to backend via POST /api/check_originality
body: JSON.stringify({ title, abstract })
```

### What the Backend Accepts and Uses
In [`backend/app.py`](file:///c:/Users/prashanth/Desktop/student_project_mgmt/backend/app.py#L2183-L2205), the API endpoint `@app.route('/api/check_originality', methods=['POST'])` extracts five potential fields:
- `title = data.get("title", "")` *(Mandatory)*
- `abstract = data.get("abstract", "")` *(Mandatory)*
- `objectives = data.get("objectives", "")` *(Optional, defaults to empty string)*
- `methodology = data.get("methodology", "")` *(Optional, defaults to empty string)*
- `description = data.get("description", "")` *(Optional, defaults to empty string)*

> [!NOTE]
> **Validation Rule in Code:**  
> `if not abstract or not title: return jsonify({"error": "Both title and abstract are required"}), 400`  
> In normal student usage, the student only provides **Title** and **Abstract**. If `objectives`, `methodology`, or `description` are missing or blank, the backend algorithm automatically falls back to using the `abstract` for those section comparisons.

---

## 2. Complete Originality Checking Flow

```
Student enters Title & Abstract
                ↓
[Frontend: team-dasboard.html]
submitProject() triggers modal: "Checking originality..."
                ↓
HTTP POST Request to /api/check_originality with { title, abstract }
                ↓
[Backend: app.py] check_originality()
Validates payload (checks title and abstract exist)
                ↓
Database Query: Retrieves existing projects
Fetches from MongoDB db.projects + db.teams (project_idea & project_ideas)
                ↓
IntelligentOriginalityEngine.evaluate(submission, db_projects)
Text Preprocessing: Sentence splitting, Keyword extraction, Normalization
                ↓
Comparison Loop over EVERY existing project in DB:
    1. Exact Phrase Matching (Substring & Sentence equality)
    2. Semantic Similarity (SentenceTransformer all-MiniLM-L6-v2)
    3. Section TF-IDF Cosine Similarity (Scikit-Learn TfidfVectorizer)
    4. Keyword Similarity (Curated Tech keywords + non-stopwords)
    5. N-gram Overlap (Unigrams, Bigrams, Trigrams)
    6. Fuzzy String Matching (SequenceMatcher ratio)
                ↓
Composite Similarity Calculation:
Composite Score = 0.30*Semantic + 0.25*TFIDF + 0.15*Exact + 0.15*Ngram + 0.10*Keyword + 0.05*Fuzzy
Similarity % = Composite Score × 100
                ↓
Database Selection:
Sorts all projects descending by similarity.
Selects highest similarity project as top_1 (max_sim).
                ↓
Originality Calculation:
Originality % = 100.0 - max_sim
                ↓
Threshold & Status Decision:
- If max_sim > 25%: Genuine match detected with top project.
- If max_sim <= 25%: "No significantly similar project found in the existing database."
- Confidence level computed (High / Medium based on distance from 50%).
- Generates Section Analysis & Heuristic AI Mentor Suggestions.
                ↓
Backend responds with JSON:
{ similarity_percent, originality_score, most_similar_project, top_matching_projects, section_analysis, overall_suggestions, confidence, highlighted_similar_text }
                ↓
[Frontend: team-dasboard.html]
renderOriginalityReport(data) displays interactive report cards in modal
                ↓
50% Hard Threshold Gate (Frontend Code):
- IF similarity_percent > 50%:
      Alert: "Similarity > 50%. Project rejected automatically."
      EXECUTION STOPS. Idea is NOT submitted.
- IF similarity_percent <= 50%:
      Calls POST /api/team/save_project_idea
      Idea stored in MongoDB with status: "Pending Faculty Approval".
```

---

## 3. How Does It Match Two Project Ideas?

This is the central matching engine. It does **not** rely on just one technique. Instead, the class [`IntelligentOriginalityEngine`](file:///c:/Users/prashanth/Desktop/student_project_mgmt/backend/app.py#L1490-L2053) uses a **6-layer hybrid ensemble**:

### Text Preparation
Before comparing, the engine creates two representations:
1. **Full concatenated text:**  
   `sub_full_text = f"{sub_title}. {sub_abstract} {sub_objectives} {sub_methodology} {sub_description}".strip()`
2. **Section dictionary:**  
   `sub_dict = {"title": sub_title, "abstract": sub_abstract, "objectives": sub_objectives, "methodology": sub_methodology, "description": sub_description}`

### The 6 Matching Techniques Used in Code

| # | Technique | What it Compares | Algorithm / Model Used | Weight in Score |
|---|-----------|-------------------|-------------------------|-----------------|
| 1 | **Semantic Similarity** | Full text vs Full text | `SentenceTransformer('all-MiniLM-L6-v2')` + Cosine similarity (`util.cos_sim`) | **30% (0.30)** |
| 2 | **Section TF-IDF Cosine Similarity** | Section by Section (Title, Abstract, Objectives, Methodology, Description) | `sklearn.feature_extraction.text.TfidfVectorizer(ngram_range=(1, 2))` + `sklearn.metrics.pairwise.cosine_similarity` | **25% (0.25)** |
| 3 | **Exact Phrase Matching** | Sentence by sentence | Regex sentence splitting + Normalized exact match & substring search | **15% (0.15)** |
| 4 | **N-gram Similarity** | Full text tokens | Unigrams (1-word), Bigrams (2-word), Trigrams (3-word) Jaccard-style overlap | **15% (0.15)** |
| 5 | **Keyword Similarity** | Extracted tech & domain terms | Set intersection against 50+ curated `TECH_KEYWORDS` + extracted nouns | **10% (0.10)** |
| 6 | **Fuzzy String Matching** | (Title + Abstract) vs (Title + Abstract) | Python `difflib.SequenceMatcher.ratio()` (Ratcliff-Obershelp gestalt pattern matching) | **5% (0.05)** |

### Answers to Specific Match Questions:
- **What parts of the text are compared?**  
  Title, Abstract, Objectives, Methodology, Description. When students submit only Title and Abstract, the engine uses the Title and Abstract, and automatically cascades the Abstract into the empty sections.
- **Are title and abstract combined?**  
  **Yes.** For semantic similarity, n-grams, and keyword matching, they are concatenated into `full_text`. For fuzzy matching, `sub_title + " " + sub_abstract` is compared.
- **Are keywords used?**  
  **Yes.** Curated set of `TECH_KEYWORDS` (e.g. `react`, `cnn`, `machine learning`, `blockchain`, `iot`, `tensorflow`, `pytorch`, etc.) plus words > 3 characters not in `STOP_WORDS`.
- **Is exact word/phrase matching used?**  
  **Yes.** Normalized sentences are checked for 100% exact matches (`+1.0`) or substring containment (`+0.8`).
- **Is semantic similarity used?**  
  **Yes.** Dense vector semantic similarity.
- **Is TF-IDF used?**  
  **Yes.** Section-wise TF-IDF with unigrams and bigrams (`ngram_range=(1, 2)`).
- **Are embeddings used?**  
  **Yes.** 384-dimensional dense vectors from Sentence Transformers.
- **Is machine learning / deep learning used?**  
  **Yes.** Pre-trained transformer neural network (`all-MiniLM-L6-v2`).
- **Is an LLM used for matching?**  
  **No.** Matching is done locally using Sentence Transformers and Scikit-Learn. (Gemini API is defined in code for text suggestions, but is not used to calculate similarity).
- **Is Sentence Transformer used?**  
  **Yes.** Specifically `SentenceTransformer('all-MiniLM-L6-v2')`.
- **Is cosine similarity used?**  
  **Yes, in two distinct places:**  
  1. Vector cosine similarity between sentence transformer embeddings (`util.cos_sim`).  
  2. Cosine similarity between TF-IDF sparse vectors (`sklearn.metrics.pairwise.cosine_similarity`).

---

## 4. Which Model is Actually Used?

Here are the exact facts from the code:

- **Exact Model Name:** `'all-MiniLM-L6-v2'`
- **Library / Package:** `sentence-transformers` (supported by PyTorch and Hugging Face Transformers)
- **Where Loaded:** [`backend/app.py`](file:///c:/Users/prashanth/Desktop/student_project_mgmt/backend/app.py#L1461-L1466):
  ```python
  try:
      similarity_model = SentenceTransformer('all-MiniLM-L6-v2')
  except Exception as _e:
      print(f"Notice loading SentenceTransformer: {_e}")
      similarity_model = None
  ```
- **Where Assigned to Engine:** [`backend/app.py`](file:///c:/Users/prashanth/Desktop/student_project_mgmt/backend/app.py#L1491-L1493):
  ```python
  class IntelligentOriginalityEngine:
      def __init__(self):
          self.model = similarity_model
  ```
- **Which Function Uses It:** [`compute_semantic_similarity(self, sub_full_text, db_full_text)`](file:///c:/Users/prashanth/Desktop/student_project_mgmt/backend/app.py#L1618-L1628)
- **What Input is Given to It:**
  ```python
  embeddings = self.model.encode([sub_full_text, db_full_text], convert_to_tensor=True)
  ```
  It receives a Python list of two strings: the submitted project's full text and the database project's full text.
- **What Output It Produces:**  
  A PyTorch tensor containing two 384-dimensional vectors of 32-bit floating-point numbers.
- **What That Output Means:**  
  Each 384-dimensional vector represents the semantic meaning of the entire text in a continuous vector space. If two texts discuss the same topic using different words, their 384-dimensional coordinates point in nearly the same directional angle.

---

## 5. What is an Embedding?

In simple terms, an **embedding** is a way to turn human sentences into a list of numbers so a computer can compare meaning instead of just spelling.

```
"AI crop disease detector"
         ↓
Sentence Transformer Model
         ↓
[-0.042, 0.128, 0.009, -0.071, ..., 0.083]  (List of 384 numbers)
```

### Why Similar Sentences Have Similar Vectors
- Traditional keyword search looks for exact letters. If one project says *"Crop disease detection"* and another says *"Plant leaf infection diagnosis"*, exact word search sees 0% overlap.
- The `all-MiniLM-L6-v2` neural network was trained on over 1 billion sentence pairs to understand that:
  - *"crop"* is conceptually related to *"plant"* and *"leaf"*.
  - *"disease"* is conceptually related to *"infection"*.
  - *"detection"* is conceptually related to *"diagnosis"*.
- When the model transforms both texts into numbers, it places both vectors pointing in virtually the same direction in 384-dimensional space.
- The angle between them is tiny, resulting in a high similarity score.

---

## 6. How is Similarity Calculated?

The system calculates similarity in two phases: individual component scores and a weighted combination.

### Phase A: The 6 Sub-Calculations

#### 1. Semantic Similarity (Cosine Similarity on Embeddings)
```
Vector A = model.encode(submission_text)
Vector B = model.encode(db_project_text)
semantic_score = util.cos_sim(Vector A, Vector B)
```
Formula:
$$\text{Cosine Similarity} = \frac{\mathbf{A} \cdot \mathbf{B}}{\|\mathbf{A}\| \|\mathbf{B}\|}$$
Range: `0.0` to `1.0`.

#### 2. Section TF-IDF Cosine Similarity
Calculated section by section using weights:
- Title: `0.10`
- Abstract: `0.35`
- Objectives: `0.15`
- Methodology: `0.20`
- Description: `0.20`

For each section:
1. Words are converted to TF-IDF vectors (term frequency-inverse document frequency) with unigrams and bigrams (`ngram_range=(1,2)`).
2. Cosine similarity between sparse TF-IDF vectors is calculated:
   ```python
   sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
   ```
3. Weighted sum across sections gives `tfidf_score`.

#### 3. Exact Phrase Matching
```python
score = min(1.0, match_count / max(1, len(sub_sentences)))
```
- Full sentence match = `+1.0`
- Substring match (> 15 chars) = `+0.8`
- Divided by total number of sentences in the submission.

#### 4. N-gram Similarity
Splits text into 1-word, 2-word, and 3-word chunks (stop words removed):
```
1-gram overlap × 0.20 + 2-gram overlap × 0.35 + 3-gram overlap × 0.45
```
Where each overlap is:
$$\text{overlap} = \frac{|\text{sub\_ngrams} \cap \text{db\_ngrams}|}{\min(|\text{sub\_ngrams}|, |\text{db\_ngrams}|)}$$

#### 5. Keyword Similarity
Identifies keywords from the curated tech list + long non-stop words:
$$\text{kw\_score} = \frac{|\text{sub\_keywords} \cap \text{db\_keywords}|}{\min(|\text{sub\_keywords}|, |\text{db\_keywords}|)}$$

#### 6. Fuzzy Similarity
Uses Python's built-in `difflib.SequenceMatcher`:
$$\text{fuzzy\_score} = \frac{2 \times M}{T + D}$$
Where $M$ is the number of matching characters, and $T, D$ are the total lengths of the normalized title+abstract strings.

---

### Phase B: Final Composite Formula
In [`backend/app.py` line 2033](file:///c:/Users/prashanth/Desktop/student_project_mgmt/backend/app.py#L2033-L2042):

$$\text{Composite Score} = (0.30 \times \text{semantic}) + (0.25 \times \text{tfidf}) + (0.15 \times \text{exact}) + (0.15 \times \text{ngram}) + (0.10 \times \text{kw}) + (0.05 \times \text{fuzzy})$$

$$\text{Similarity Percentage} = \min(100.0, \max(0.0, \text{Composite Score} \times 100.0))$$

---

## 7. How Does It Get a Particular Percentage?

Suppose the sub-scores for comparing Project A against Project B are:
- Semantic similarity = `0.80`
- TF-IDF similarity = `0.60`
- Exact phrase matching = `0.20`
- N-gram similarity = `0.40`
- Keyword similarity = `0.70`
- Fuzzy similarity = `0.50`

The system calculates:
$$\text{Composite Score} = (0.30 \times 0.80) + (0.25 \times 0.60) + (0.15 \times 0.20) + (0.15 \times 0.40) + (0.10 \times 0.70) + (0.05 \times 0.50)$$
$$\text{Composite Score} = 0.24 + 0.15 + 0.03 + 0.06 + 0.07 + 0.025 = 0.575$$

$$\text{Similarity Percentage} = 0.575 \times 100 = 57.5\%$$

### How is Originality Calculated?
In [`backend/app.py` line 2083](file:///c:/Users/prashanth/Desktop/student_project_mgmt/backend/app.py#L2083):
```python
originality_score = round(max(0.0, 100.0 - max_sim), 2)
```
The code **explicitly** uses:
$$\text{Originality Score} = 100.0 - \text{Maximum Similarity Percentage}$$

For `Similarity = 57.5%`:
$$\text{Originality Score} = 100.0 - 57.5 = 42.5\%$$

---

## 8. Multiple Existing Projects

What happens when there are 10, 50, or 100 existing projects in MongoDB?

```
Submitted Project Idea
          │
          ├── vs Project 1 ──> Similarity: 18.4%
          ├── vs Project 2 ──> Similarity: 68.2%
          ├── vs Project 3 ──> Similarity: 34.1%
          └── vs Project N ──> Similarity: 12.0%
```

### Exactly What the Code Does:
In [`backend/app.py` lines 1995–2060](file:///c:/Users/prashanth/Desktop/student_project_mgmt/backend/app.py#L1995-L2060):
1. The system loops through **every single project** registered in `db.projects` and in `db.teams` (`project_idea` and `project_ideas`).
2. It calculates the individual similarity score for each project and appends it to `project_results`.
3. It sorts the array in descending order:
   ```python
   project_results.sort(key=lambda x: x["similarity_percent"], reverse=True)
   ```
4. **How the final score is selected:**
   - It takes the **HIGHEST** similarity:
     ```python
     top_1 = top_5[0] if top_5 else None
     max_sim = top_1["similarity_percent"]
     most_similar_title = top_1["title"]
     ```
   - It does **NOT** average them.
   - It takes the single project that is most similar to the submission (`top_1`).
   - The top 5 matches (`top_5`) are returned as `top_matching_projects` for display in the detailed report.

---

## 9. Complete Realistic Example

### New Project Submitted
- **Title:** `"AI Based Crop Disease Detection"`
- **Abstract:** `"An AI system that detects crop diseases using leaf images collected from farmers. It classifies plant pathologies using deep learning convolutional neural networks."`

### Existing Project in Database
- **Title:** `"Machine Learning Based Plant Disease Detection"`
- **Abstract:** `"A machine learning system that identifies plant diseases from leaf images. The model utilizes deep neural networks to recognize crop diseases."`

---

### Step-by-Step Execution Trace

#### Step 1: Student Submits
Student fills the two textboxes in `team-dasboard.html` and clicks **"Submit & Check Originality"**.

#### Step 2: API Receives Request
`POST /api/check_originality` receives `{ title: "...", abstract: "..." }`.

#### Step 3: Text Preprocessing
- Splits submission into sentences:
  - Sentence 1: *"An AI system that detects crop diseases using leaf images collected from farmers."*
  - Sentence 2: *"It classifies plant pathologies using deep learning convolutional neural networks."*
- Extracts keywords: `{'crop', 'disease', 'leaf', 'deep learning', 'neural network', 'cnn', 'images', 'pathologies'}`

#### Step 4: Existing Project Retrieved
MongoDB returns the existing project titled *"Machine Learning Based Plant Disease Detection"*.

#### Step 5: Six Algorithms Run *(Illustrative Values)*
1. **Semantic Similarity (all-MiniLM-L6-v2):**  
   Both texts encode concepts of crops, leaves, plant diseases, and deep learning.  
   $\text{cos\_sim} = \mathbf{0.84}$ (84% semantic alignment).
2. **Section TF-IDF Cosine:**  
   Title and abstract share terms (`crop`, `disease`, `detection`, `leaf`, `images`, `deep`, `learning`).  
   $\text{tfidf\_score} = \mathbf{0.68}$.
3. **Exact Phrase Matching:**  
   Sentences share phrases like *"detects crop diseases using leaf images"*, but aren't identical sentence strings.  
   $\text{exact\_score} = \mathbf{0.20}$.
4. **N-gram Overlap:**  
   Unigrams & bigrams share `crop disease`, `leaf images`, `deep learning`.  
   $\text{ngram\_score} = \mathbf{0.55}$.
5. **Keyword Overlap:**  
   Overlap of tech keywords (`deep learning`, `neural network`, `leaf`, `disease`).  
   $\text{kw\_score} = \mathbf{0.75}$.
6. **Fuzzy Ratio:**  
   Character-level SequenceMatcher on title and abstract.  
   $\text{fuzzy\_score} = \mathbf{0.62}$.

#### Step 6: Composite Similarity Calculated
$$\text{Composite} = (0.30 \times 0.84) + (0.25 \times 0.68) + (0.15 \times 0.20) + (0.15 \times 0.55) + (0.10 \times 0.75) + (0.05 \times 0.62)$$
$$\text{Composite} = 0.252 + 0.170 + 0.030 + 0.0825 + 0.075 + 0.031 = 0.6405$$
$$\text{Similarity Percentage} = \mathbf{64.05\%}$$

#### Step 7: Originality Score Calculated
$$\text{Originality Score} = 100.0 - 64.05 = \mathbf{35.95\%}$$

#### Step 8: Threshold and Metadata Evaluation
- `max_sim` (64.05%) > 25% threshold:  
  `status_msg = "Similarities detected with existing database project 'Machine Learning Based Plant Disease Detection'."`
- `confidence = "High (89%)"` (calculated from distance from 50%).
- Domain Heuristics: Matches agriculture keywords (`crop`, `farm`, `leaf photo`, `plant`), generating 10 agriculture-specific recommendations (e.g. soil telemetry, hyper-local weather, multispectral imagery).

#### Step 9: Backend Responds to Frontend
Returns JSON containing `similarity_percent: 64.05`, `originality_score: 35.95`, `most_similar_project: "Machine Learning Based Plant Disease Detection"`, etc.

#### Step 10: Frontend Decision Gate
In `team-dasboard.html`:
```javascript
if (data.similarity_percent > 50) {
  alert("Similarity > 50%. Project rejected automatically.");
  return;
}
```
Because `64.05% > 50%`:
1. The student sees an alert: **"Similarity > 50%. Project rejected automatically."**
2. The submission stops immediately.
3. The project idea is **NOT** sent to faculty.

---

## 10. The 50% Threshold: Code vs Documentation

The project documentation mentions a **50% originality threshold**. Here is what is in the code versus what is in the report:

### What is Actually Implemented in Code:
1. **Frontend Gate in [`team-dasboard.html` lines 981–985](file:///c:/Users/prashanth/Desktop/student_project_mgmt/frontend/team-dasboard.html#L981-L985):**
   ```javascript
   // ✅ Auto reject if similarity above 50%
   if (data.similarity_percent > 50) {
     alert("Similarity > 50%. Project rejected automatically.");
     return;
   }
   ```
   - If **Similarity > 50%** (which means **Originality < 50%**), the project is **automatically rejected right on the spot**.
   - The API call to [`/api/team/save_project_idea`](file:///c:/Users/prashanth/Desktop/student_project_mgmt/frontend/team-dasboard.html#L988) is skipped entirely.
   - The idea is **never saved to the database**, and never shown to faculty.
2. **If Similarity <= 50% (Originality >= 50%):**
   - The frontend calls `POST /api/team/save_project_idea`.
   - The project is saved in MongoDB under `db.teams` with `"status": "Pending Faculty Approval"`.
   - Faculty can then review it on their dashboard and click **Approve** or **Reject**.
3. **Backend 25% Threshold in [`backend/app.py` line 2062](file:///c:/Users/prashanth/Desktop/student_project_mgmt/backend/app.py#L2062):**
   - `SIMILARITY_THRESHOLD = 25.0`: The backend uses 25% internally to decide whether to label a project as having a "genuine match" or "No significantly similar project found".
4. **UI Color Banding:**
   - `> 50% Similarity`: Red banner (`#991b1b`)
   - `25% - 50% Similarity`: Orange/Amber banner (`#b45309`)
   - `< 25% Similarity`: Green banner (`#065f46`)

### What is Mentioned in Documentation / Report:
- Documentation often phrases this as an *"Originality Threshold of 50%"*. In the implementation, this is mathematically identical because $\text{Originality} = 100 - \text{Similarity}$. A similarity greater than 50% is the exact same condition as an originality less than 50%.
- The documentation implies Google Gemini API generates the 5 dynamic improvement suggestions. In the actual code, the Gemini API function (`call_gemini_api_with_retry`) exists at line 2140 of `backend/app.py`, but it is **not called** by the originality checking route; instead, the system runs local heuristic domain-based AI mentor suggestions (`generate_ai_mentor_suggestions`).

---

## 11. Code Files Involved in Originality Checking

Only three primary files are directly involved in originality checking:

### 1. `frontend/team-dasboard.html`
- **Purpose:** Student UI for submitting project ideas and viewing originality reports.
- **Important Functions:**
  - `submitProject()`: Reads `projectTitle` and `projectAbstract`, sends POST to `/api/check_originality`, enforces the 50% auto-rejection threshold, and if passed, saves via `/api/team/save_project_idea`.
  - `renderOriginalityReport(data)`: Renders the visual score badges, match cards, sentence highlights, section analysis, and recommendations.
  - `loadProjectIdeaStatus(data)`: Displays the current approval status and originality score on the student dashboard.

### 2. `backend/app.py`
- **Purpose:** Flask server containing the complete NLP originality evaluation engine and endpoints.
- **Important Functions & Classes:**
  - `similarity_model = SentenceTransformer('all-MiniLM-L6-v2')`: Loads the transformer model into memory at startup.
  - `class IntelligentOriginalityEngine`:
    - `compute_semantic_similarity()`: Uses `SentenceTransformer` and PyTorch `util.cos_sim` to get embedding cosine similarity.
    - `compute_section_tfidf_similarity()`: Computes TF-IDF cosine similarity weighted across title, abstract, objectives, methodology, and description.
    - `compute_exact_phrase_matching()`: Finds sentence-level and substring matches.
    - `compute_ngram_similarity()`: Computes unigram, bigram, and trigram Jaccard-style token overlap.
    - `compute_keyword_similarity()`: Checks overlap of technical keywords.
    - `compute_fuzzy_similarity()`: Character ratio matching using `difflib.SequenceMatcher`.
    - `generate_section_analysis()`: Evaluates abstract, objectives, methodology, and tech stack.
    - `generate_ai_mentor_suggestions()`: Rules-based domain suggestion generator (healthcare, agriculture, ecommerce, drone logistics, security, education, finance).
    - `evaluate()`: Runs all 6 comparisons against all DB projects, sorts, picks max similarity, calculates `originality_score = 100 - max_sim`, and formats top 5 matches.
  - `@app.route('/api/check_originality', methods=['POST'])`: Route receiving student inputs and returning the JSON report.
  - `@app.route('/api/team/save_project_idea', methods=['POST'])`: Saves the passed idea with its originality scores into MongoDB for faculty approval.

### 3. `frontend/faculty-dashboard.html`
- **Purpose:** Faculty UI to review student submissions and run standalone novelty checks.
- **Important Functions:**
  - `facultyCheckNovelty()`: Allows faculty to enter any title and abstract and test against the database using `/api/check_originality`.
  - `renderOriginalityReport(data)`: Identical rendering function displaying detailed match analytics to faculty.

---

## 12. Final Simple Explanations (For Interviews & Viva)

### Fill-in-the-Blanks Summary
> "Our system takes the student's project title and abstract and compares them with previously submitted project ideas in our MongoDB database. The text is processed using **sentence splitting, text normalization, and technical keyword extraction**. Then **a hybrid ensemble of Sentence Transformers (`all-MiniLM-L6-v2`), Section-wise TF-IDF, N-gram overlap, exact sentence matching, and fuzzy matching** is used to represent and compare the text. The system calculates **a weighted composite similarity score using cosine similarity and token overlap** and converts it into a **percentage from 0% to 100%**. The originality score is calculated as **100 minus the maximum similarity percentage**. Based on the 50% threshold, the system **automatically rejects the project if similarity exceeds 50%, or forwards it to the faculty supervisor with a 'Pending Faculty Approval' status if similarity is 50% or below**."

---

### ONE-LINE ANSWER
> *"Our project uses a 6-layer hybrid matching engine combining `all-MiniLM-L6-v2` Sentence Transformer embeddings, section-wise TF-IDF cosine similarity, and n-gram overlap to compute a similarity score against all existing projects, where originality equals 100 minus the highest similarity."*

---

### 30-SECOND ANSWER
> *"When a student submits a project title and abstract, our Flask backend queries all existing projects from MongoDB. It compares the submission against each existing project across six weighted techniques: 30% Sentence Transformer semantic similarity, 25% section-wise TF-IDF cosine similarity, 15% exact sentence matching, 15% n-gram overlap, 10% tech keyword matching, and 5% fuzzy matching. It picks the highest similarity match in the database, subtracts it from 100 to get the originality score, and if similarity exceeds 50%, the project is automatically rejected on the frontend before reaching faculty."*

---

### 1-MINUTE TECHNICAL ANSWER
> *"The originality checking module is an ensemble NLP system implemented in `backend/app.py`. When a student submits a title and abstract from `team-dasboard.html`, the backend compares the submission against every registered project in the database.*  
>  
> *For semantic similarity, it generates 384-dimensional dense vector embeddings using the `all-MiniLM-L6-v2` Sentence Transformer model and computes PyTorch cosine similarity. For syntactic and lexical similarity, it runs Scikit-Learn TF-IDF vectorization across sections (title, abstract, objectives, methodology), unigram-bigram-trigram token overlap, curated tech keyword matching, exact sentence matching, and fuzzy sequence matching.*  
>  
> *These six scores are combined using fixed weights into a composite similarity percentage. The system identifies the most similar project in the database, and computes the originality score as `100 - max_similarity`. If similarity exceeds 50%, the frontend automatically rejects the idea; otherwise, the idea and its scores are saved to MongoDB with a 'Pending Faculty Approval' status for supervisor evaluation."*
