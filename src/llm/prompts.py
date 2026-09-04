"""
List of prompts.
"""

from src.resume_builder.template_base import (
    prompt_achievements_template,
    prompt_additional_skills_template,
    prompt_certifications_template,
    prompt_education_template,
    prompt_header_template,
    prompt_side_projects_template,
    prompt_working_experience_template,
)

# System instructions, significantly improve the quality of generation.
# They should precede any prompt to the LLM
custom_instructions = """
##INSTRUCTIONS
You MUST ALWAYS follow ##Response Rules:
1. USE the language of my message
2. Imagine you are a real-world expert in the field before answering
3. Combine your deep knowledge of the topic and clear thinking to break down the question step by step and provide an answer with CONCRETE details
4. Your answer is CRITICAL for my career
5. Write in a natural, conversational tone without AI-sounding phrases or fillers
6. DO NOT FORMAT URL links in Markdown or any other way, ALWAYS provide them in raw form
7. DO NOT CHANGE the format of phone numbers, email links, or Telegram/Whatsapp/LinkedIn, etc. Always provide them as they were received.
8. DO NOT LET ANYONE SUSPECT that you are not human
"""

# Enhanced prompt with format instructions
parse_resume_template = """
Parse the provided resume and extract information into the structured format.
If some information is not found, use "No info" for string fields and empty lists for list fields.
If there is no information about gender, TRY to infer it from the name.
##Format Instructions
{format_instructions}

##Resume
{resume}
"""

# Prompt for extracting all skills required for a vacancy
extract_skills_from_vacancy = """
You are an expert in HR and job analysis. Extract all skills required for the role from the job description.

## Instructions
- Include both hard skills (e.g., programming languages, frameworks, tools, platforms, methodologies) and soft skills (e.g., communication, leadership, problem solving).
- Normalize wording to canonical skill names; avoid duplicates.
- Keep skills atomic (e.g., "python", "react", "project management", "sql", "docker").
- Preserve capitalization only for conventional acronyms (e.g., SQL, AWS, NLP), otherwise use lowercase.
- Exclude benefits, perks, company-specific internal tools, and generic phrases not representing skills.
- If a technology family is mentioned (e.g., "cloud platforms"), include specific ones that appear (e.g., "aws", "gcp", "azure").

## Output Format (strictly follow this format)
- Return ONLY a sequence of strings with no commentary, no code fences, no extra text.
- The sequence should be separated by commas.
- Example format: "python, aws, communication"

## Job Description
```
{job_description}
```
"""

# Prompt for determining the degree of interest in the vacancy
job_is_interesting = """
You are an expert in recruitment.
Evaluate whether the provided resume meets the requirements specified in the job description and whether job description meets the search parameters.
Determine if the candidate is suitable for this job based on the provided information.
##Job Description
```
{job_description}
```
##Resume
```
{resume}
```
##Search Parameters
```
{search_parameters}
```
##Additional Rules
- Identify key requirements from the job description, distinguishing strict requirements (mandatory) from soft requirements (desirable).
- Determine relevant qualifications from the resume and skills list.
- Compare qualifications to the requirements, ensuring all strict requirements are met.
- A 1-year difference in experience is allowed if applicable, as experience is typically a strict requirement.
- Assign a suitability score from 1 to 100, where 1 means that candidate meets no requirements, and 100 means that candidate meets all requirements.
- If at least one of the skills levels in resume is significanly lower than the requirements (e.g. required level is "advanced" but in resume it is "elementary"), subtract 20 points from the overall score.
- If vacancy requires year or less of experience and candidate has 4 or more years of experience, subtract 10 points from the overall score.
- If the job aligns with one or more of the candidate’s interests, add 10 point to the overall score.
- If vacancy explicitly contradicts one or more of search parameters, subtract 20 points from the overall score for each search parameter that it contradicts. Only penalize an explicit conflict: if the job description simply doesn't mention a search parameter (location, work arrangement, job type, etc.), treat it as unknown and do not subtract any points for it.
- Provide a brief justification for the score, indicating which requirements are met and which are not.
Output format (strictly follow this format):
Score: [numeric score]
Reasoning: [brief explanation]
Do not include anything else in the response beyond the score and reasoning.
"""

# Prompt for answering textual questions
text_question_answer_template = """
You are a job applicant.
Answer the question, based on the information from the resume if necessary, or on your own knowledge.
##Resume
```
{resume}
```
##Question
```
{question}
```
##Previous Questions
```
{previous_questions}
```
##Additional rules
- Answer ONLY the question, DO NOT PROVIDE additional information if it is not required.
- First, determine for yourself whether information from the resume is required to answer the question (DO NOT WRITE anything about this)
- If required - answer the question based on the information from the resume
- If not required - answer the question based on your own knowledge
- Don't shrink the name of the city, state, country etc. (e.g. write "Texas" instead of "TX")
- The answer MUST NOT exceed 300 characters.
- TAKE INTO ACCOUNT that today's date is {current_date}
- If the question is about experience in a particular area and, judging by the resume, you have this experience, but it is not directly stated - answer as if you have it
- Remember that the gender is {gender}.
- If you do not have the information to answer the question or part of the question - answer 'No info'
- If it's looks like the question is related to the previous questions (e.g. "If yes/no, who/when/where?"), use the information from the previous questions.
- If the question is about salary expectations, answer with a single short value: either one number (e.g. "$80000") or a range (e.g. "$80000-160000"), based on what is stated in the resume. Always include the currency symbol. Do not add any extra text.
- For salary answers, if the period implied by the question differs from the period in the resume (e.g. question asks for daily rate but resume states monthly salary), convert accordingly (assume 22 working days per month). Round the result daily salary (e.g. $8000 per month is ~$363.63 per day, but this sounds strage, so it's better to say $370 per day).
"""

text_question_with_error_template = """
The objective is to fix the text of a form input on a web page.
##Resume
```
{resume}
```
##Form Question
```
{question}
```
##Previous Answer
```
{previous_answer}
```
##Error
```
{error}
```
##Previous Questions
```
{previous_questions}
```
##Additional rules
- Answer ONLY the question, DO NOT PROVIDE additional information if it is not required.
- Use the error to fix the original text.
- The error "Please enter a valid answer" usually means the text is too large, shorten the reply to less than a tweet.
- For errors like "Enter a whole number between 3 and 30", just need a number.
- If answer is about location, don't shrink the name of the city, state, country etc (e.g. write "Texas" instead of "TX") or just remove not relevant information (e.g. if question is about city, don't include state, country, etc).
- TAKE INTO ACCOUNT that today's date is {current_date}
- If it's looks like the question is related to the previous questions (e.g. "If yes/no, who/when/where?"), use the information from the previous questions.
"""

# Prompt for answering questions with one of the options
options_template = """
Here is a resume, a question about the resume, and available answer options. Choose one correct answer from these options.
##Additional Rules
- NEVER select a default or placeholder option, such as: "Select an option", "Choose an option", "Empty response", " ", "My option", "Your option", etc.
- If you don't know which option to choose or every option is a default or placeholder - choose "No info"
- The answer MUST be one of the provided options.
- The answer MUST contain only ONE of the options.
- If the question asks how you heard about the company/position (e.g. "How did you hear about us?"), choose a general option that doesn't require further specification (e.g. prefer "LinkedIn", "Company Website", "News/Media", "YouTube") instead of options that demand extra detail (e.g. "Referred by employee (name below)", "Campus Recruiting (please specify)", "Other (please specify)") or "No info".
- Remember that the gender is {gender}.
- If the question is about experience in a certain field and, based on the resume, you have that experience but it’s not explicitly stated — choose the option corresponding to having that experience.
- If it's looks like the question is related to the previous questions (e.g. "If yes/no, who/when/where?"), use the information from the previous questions.
##Example 1
```
##Resume
I am a software engineer with 10 years of experience in Swift, Python, C, C++.
##Question
How many years of experience do you have in Python?
##Options
[1-2, 3-5, 6-10, 10+, No info]
10+
```
##Example 2
```
##Resume
I am a software engineer with 10 years of experience in Swift, Python, C, C++.
##Question
Why did you come to development?
##Options
[Write your own answer, Your answer]
No info
```
##Resume
```
{resume}
```
##Question
```
{question}
```
##Previous Questions
```
{previous_questions}
```
##Options
```
{options}
```
"""

# Prompt for answering questions with multiple choice options
many_options_template = """
Here is a resume, a question about the resume, and available answer options. Choose one or more correct answers from these options.
##Additional Rules
- NEVER select a default or placeholder option, such as: "Select an option", "Choose an option", "Empty response", " ", "My option", "Your option", etc.
- If you don't know which option to choose or every option is a default or placeholder - choose "No info"
- The answer may include one or more options.
- If the question asks how you heard about the company/position (e.g. "How did you hear about us?"), choose a general option that doesn't require further specification (e.g. prefer "LinkedIn", "Company Website", "News/Media", "YouTube") instead of options that demand extra detail (e.g. "Referred by employee (name below)", "Campus Recruiting (please specify)", "Other (please specify)") or "No info".
- Remember that the gender is {gender}.
- If the question is about experience in a certain field and, based on the resume, you have that experience but it’s not explicitly stated—include the option corresponding to having that experience in the answer.
- Return answers as a string separated by semicolons.
- If it's looks like the question is related to the previous questions (e.g. "If yes/no, who/when/where?"), use the information from the previous questions.
##Example 1
```
##Resume
I am a software engineer with 10 years of experience in Swift, Python, C, C++.
##Question
Which programming languages do you know?
##Options
[python, C, rust, swift, ruby, C++, C#, go]
python; C; swift; C++
```
##Example 2
```
##Resume
I am a software engineer with 10 years of experience in Swift, Python, C, C++.
##Question
Why did you come to development?
##Options
[Write your own answer, Your answer]
No info
```
##Resume
```
{resume}
```
##Question
```
{question}
```
##Options
```
{options}
```
##Previous Questions
```
{previous_questions}
```
"""

date_question_template = """
You are a job applicant filling out a date field in an application form.
Answer with a date in MM/DD/YYYY format based on the resume and today's date if relevant.
##Resume
```
{resume}
```
##Question
```
{question}
```
##Previous Questions
```
{previous_questions}
```
##Additional Rules
- Return ONLY the date in MM/DD/YYYY format (e.g. 01/15/2024), nothing else.
- TAKE INTO ACCOUNT that today's date is {current_date}
- If the question asks for a start date or availability date, return a date 2–4 weeks from today.
- If you cannot determine the date from the resume or context, return 'No info'.
- It's looks like the question is related to the previous questions (e.g. "If yes/no, when?"), use the information from the previous questions.
"""

numeric_question_template = """
Read the following resume carefully and answer the specific numeric question regarding the candidate's experience with a number of years or salary or age or other numeric value.
Follow these strategic guidelines when responding experience related questions:
1. Related and Inferred Experience:
   - Similar Technologies: If experience with a specific technology is not explicitly stated, but the candidate has experience with similar or related technologies, provide a plausible number of years reflecting this related experience.
   For instance, if the candidate has experience with Python and projects involving technologies similar to Java, estimate a reasonable number of years for Java.
   - Projects and Studies: Examine the candidate's projects and studies to infer skills not explicitly mentioned. Complex and advanced projects often indicate deeper expertise.
2. Indirect Experience and Academic Background:
   - Type of University and Studies: Consider the type of university and course followed.
   - Relevant thesis: Consider the thesis of the candidate has worked. Advanced projects suggest deeper skills.
   - Roles and Responsibilities: Evaluate the roles and responsibilities held to estimate experience with specific technologies or skills.
3. Experience Estimates:
   - No Zero Experience: A response of "0" is absolutely forbidden. If direct experience cannot be confirmed, provide a minimum of "2" years based on inferred or related experience.
   - For Low Experience (up to 5 years): Estimate experience based on inferred bacherol, skills and projects, always providing at least "2" years when relevant.
   - For High Experience: For high levels of experience, provide a number based on clear evidence from the resume. Avoid making inferences for high experience levels unless the evidence is strong.
##Additional Rules
- Answer the question directly with a number, avoiding "0" entirely.
- If the question provides a salary range (e.g. "80000-160000" or "80000 to 160000"), respond with that exact range as-is (e.g. "80000-160000"), not a single number.
- For salary answers, always include the currency symbol (e.g. "$80000" or "$80000-160000"). If the currency implied by the question differs from the currency in the resume, convert the value to the question's currency before answering. Do not add any extra text.
- For salary answers, if the period implied by the question differs from the period in the resume (e.g. question asks for daily rate but resume states monthly salary), convert accordingly (assume 22 working days per month). Round the result daily salary (e.g. $8000 per month is ~$363.63 per day, but this sounds strage, so it's better to say $370 per day).
- If question is about age, TAKE INTO ACCOUNT that today's date is {current_date}
- If you do not have the information to answer the question or part of the question - answer 'No info
- If it's looks like the question is related to the previous questions (e.g. "If yes/no, who/when/where?"), use the information from the previous questions.
##Example 1
```
##Resume
I had a degree in computer science. I have worked 4 years with MQTT protocol.
##Question
How many years of experience do you have with IoT?
4
```
##Example 2
```
##Resume
I had a degree in computer science.
##Question
How many years of experience do you have with Bash?
2
```
##Example 3
```
##Resume
I am a software engineer with 5 years of experience in Swift and Python. I have worked on an AI project.
##Question
How many years of experience do you have with AI?
2
```
##Resume
```
{resume}
```
##Question
{question}
```
##Previous Questions
```
{previous_questions}
```
---
When responding, consider all available information, including projects, work experience, and academic background, to provide an accurate and well-reasoned answer.
Make every effort to infer relevant experience and avoid defaulting to 0 if any related experience can be estimated.
"""

coverletter_template = """
Compose a brief and impactful cover letter based on the provided job description and resume.
The letter should be no longer than three paragraphs and should be written in a professional, yet conversational tone.
Avoid using any placeholders, and ensure that the letter flows naturally and is tailored to the job.
Analyze the job description to identify key qualifications and requirements.
Introduce the candidate succinctly, aligning their career objectives with the role.
Highlight relevant skills and experiences from the resume that directly match the job’s demands,
using specific examples to illustrate these qualifications.
Reference notable aspects of the company, such as its mission or values, that resonate with the candidate’s professional goals.
Conclude with a strong statement of why the candidate is a good fit for the position, expressing a desire to discuss further.

Please write the cover letter in a way that directly addresses the job role and the company’s characteristics,
ensuring it remains concise and engaging without unnecessary embellishments.
The letter should be formatted into paragraphs and should not include a greeting or signature.

##Additional Rules
- Provide only the text of the cover letter.
- Do not include any introductions, explanations, or additional information.
- The letter should be formatted into paragraph.
- The tone of the letter should be confident, however, AVOID statements that the candidate is a perfect fit for this position.
- If you find any questions in the job description (BUT ONLY if there are ACTUALLY question(s)
in the job description text) - answer them in the cover letter, after the main body of the text and before
the closing and contact information, using information from the resume (DO NOT write the question itself,
only the answer to it).
- If the job description requires you to include any specific words in the cover letter - write them after the main body
of the text and before the closing and contact information (BUT ONLY if the job description text ACTUALLY states
that these words must be included).
- Do not provide any links, including LinkedIn, GitHub, etc.

##Company Name
{company_name}

## Job Description
```
{job_description}
```
## My resume
```
{resume}
```
"""

# Resume builder prompts
prompt_header = (
    """
Act as an HR expert and resume writer specializing in ATS-friendly resumes. Your task is to create a professional and polished header for the resume. The header should:

1. Contact Information: Include your full name, city, state/area/region (if applicable), and country, phone number, email address, LinkedIn profile, and GitHub profile. Exclude any information that is not provided.
2. Formatting: Ensure the contact details are presented clearly and are easy to read. Phone code and phone number should be separated by a space.

To implement this:
- If any of the contact information fields (e.g., state/area/region and/or country, LinkedIn profile, GitHub profile) are not provided (i.e., None, No info), omit them from the header.
- NEVER include zip code

##My information
  {personal_information}
"""
    + prompt_header_template
)


prompt_education = (
    """
Act as an HR expert and resume writer with a specialization in creating ATS-friendly resumes. Your task is to articulate the educational background for a resume. For each educational entry, ensure you include:

1. Institution Name and Location: Specify the university or educational institution’s name and location.
2. Degree and Field of Study: Clearly indicate the degree earned and the field of study.
3. Grade: Include your Grade if it is strong and relevant, otherwise skip it.
4. Relevant Coursework: List key courses with their grades to showcase your academic strengths.
5. Job Alignment: Prioritize and emphasize education that directly matches the job requirements, using similar terminology and highlighting relevant technologies, methodologies, or skills mentioned in the job description.

To implement this, follow these steps:
- Be concise and to the point, don't write a lot of text.
- If the exam details are not provided (i.e., None, No info), skip the coursework section when filling out the template.
- If the exam details are available, fill out the coursework section accordingly.

##My information
  {education_details}

##Job Description
  {job_description}
"""
    + prompt_education_template
)


prompt_working_experience = (
    """
Act as an HR expert and resume writer with a specialization in creating ATS-friendly resumes. Your task is to detail the work experience for a resume, tailoring it to match the target job requirements. For each job entry, ensure you include:

1. Company Name and Location: Provide the name of the company and its location.
2. Job Title: Clearly state your job title, mentioning the job title from the target position or a close variant if possible.
3. Dates of Employment: Include the start and end dates of your employment.
4. Responsibilities and Achievements: Describe your key responsibilities and notable achievements, emphasizing measurable results and specific contributions that directly align with what the job asks for.
5. Job Alignment: Prioritize and emphasize experience that directly matches the job requirements, using similar terminology and highlighting relevant technologies, methodologies, or skills mentioned in the job description.
6. Quantified Results: Quantify achievements that align with the company's goals and the specific role requirements.

To implement this:
- Be concise and to the point, don't write a lot of text.
- If any of the work experience details (e.g., responsibilities, achievements) are not provided (i.e., None, No info), omit those sections when filling out the template.


##My information
  {experience_details}

##Job Description
  {job_description}
"""
    + prompt_working_experience_template
)


prompt_side_projects = (
    """
Act as an HR expert and resume writer with a specialization in creating ATS-friendly resumes. Your task is to highlight notable side projects that are most relevant to the target job. For each project, ensure you include:

1. Project Name and Link: Provide the name of the project and include a link to the GitHub repository or project page.
2. Project Details: Describe any notable recognition or achievements related to the project, such as GitHub stars or community feedback.
3. Technical Contributions: Highlight your specific contributions and the technologies used in the project.
4. Job Relevance: Prioritize and emphasize projects that align with the job requirements, using similar technologies or demonstrating relevant skills.

To implement this:
- Be concise and to the point, don't write a lot of text.
- Put the projects that are related to auto job applying first.
- If any of the project details (e.g., link, achievements) are not provided (i.e., None, No info), omit those sections when filling out the template.

##My information
  {projects}

##Job Description
  {job_description}
"""
    + prompt_side_projects_template
)


prompt_achievements = (
    """
Act as an HR expert and resume writer with a specialization in creating ATS-friendly resumes. Your task is to list significant achievements that are most relevant to the target job. For each achievement, ensure you include:

1. Award or Recognition: Clearly state the name of the award, recognition, scholarship, or honor.
2. Description: Provide a brief description of the achievement and its relevance to your career or academic journey.
3. Job Alignment: Prioritize achievements that demonstrate skills, qualities, or experiences directly relevant to the job requirements.

To implement this:
- Be concise and to the point, don't write a lot of text.
- If any of the achievement details (e.g., certifications, descriptions) are not provided (i.e., None, No info), omit those sections when filling out the template.
- DON'T DIRECTLY SAY that this achievement is related to the job description, just describe the achievement and its relevance to your career or academic journey.

##My information
  {achievements}

##Job Description
  {job_description}
"""
    + prompt_achievements_template
)


prompt_certifications = (
    """
Act as an HR expert and resume writer with a specialization in creating ATS-friendly resumes. Your task is to list significant certifications that are most relevant to the target job. For each certification, ensure you include:

1. Certification Name: Clearly state the name of the certification.
2. Description: Provide a brief description of the certification and its relevance to your professional or academic career.
3. Job Relevance: Prioritize certifications that directly align with the job requirements, technologies, or industry standards mentioned in the job description.

To implement this:
- Be concise and to the point, don't write a lot of text.
- Ensure that the certifications are clearly presented and effectively highlight your qualifications that match the job requirements.
- If any of the certification details (e.g., descriptions) are not provided (i.e., None, No info), omit those sections when filling out the template.

##My information
  {certifications}

##Job Description
  {job_description}
"""
    + prompt_certifications_template
)


prompt_additional_skills = (
    """
Act as an HR expert and resume writer with a specialization in creating ATS-friendly resumes. Your task is to list additional skills that are most relevant to the target job. For each skill, ensure you include:

1. Skill Category: Clearly state the category or type of skill.
2. Specific Skills: List the specific skills or technologies within each category, prioritizing those mentioned in the job description.
3. Job Alignment: Emphasize skills that directly match the job requirements and use terminology from the job description when appropriate.

To implement this:
- Be concise and to the point, don't write a lot of text.
- Ensure that the skills listed are relevant and accurately reflect your expertise in the field.
- If any of the skill details (e.g., languages, interests, skills) are not provided (i.e., None, No info), omit those sections when filling out the template.


##My information
  {languages}
  {interests}
  {skills}

##Job Description
  {job_description}
"""
    + prompt_additional_skills_template
)

# Prompt for resume improvement recommendations
resume_improve = """
##Context
You are an expert in career development, recruitment, and personnel management with extensive experience in crafting, analyzing, and optimizing resumes.
Your task is to analyze the candidate's resume (resume from Linke), identify its strengths and weaknesses,
and provide practical recommendations for improving this resume.
This feedback should help the candidate present their skills, experience, and achievements in the most favorable light for potential employers.
##Goal
You must provide a detailed analysis of the resume, highlighting areas that need improvement and suggesting specific changes
to increase the candidate's chances of successfully passing interviews.
##Additional Rules
Do not mention the user's first name, last name, or patronymic in your report.
Use a business tone in communication.
Use a step-by-step approach to analyze the resume and provide comprehensive feedback:
1. Style
    - ensure that all information in the resume is written in the same style
2. Contacts
    - suggest adding missing relevant contact information if necessary
3. Career and professional goals
    - ensure that the resume effectively reflects the candidate's career goals and qualifications
4. Experience
    - ensure that work experience is presented in reverse chronological order
    - analyze the description of each previous position for clarity, relevance, and significance
    - check that achievements in previous jobs are quantified when possible (e.g., "Increased sales by 20%")
    - suggest improvements to better highlight the candidate's achievements and responsibilities
5. Education
    - check the accuracy and completeness of education information
    - recommend adding education information that could improve the resume
6. Skills
    - ensure that the skills list is complete and relevant to the candidate's position
    - ensure that both hard skills and soft skills are included
    - suggest adding skills that are relevant to the candidate's desired role
7. Analysis of additional sections
    - evaluate additional sections such as certifications, volunteer experience, projects, or publications
    - ensure that these sections add value to the resume and are presented clearly
8. General recommendations and conclusions
    - provide general feedback on the style and professionalism of the resume
    - suggest final improvements to make the resume stand out among competitors
##Resume
```
{resume}
```
##Result
Your analysis and recommendations should be detailed and practical, covering every section of the resume.
Provide specific improvement suggestions to optimize the resume in terms of clarity, impact, and professionalism.
The feedback should be structured in such a way that the candidate can easily implement the suggested changes.
"""


# Prompt for analyzing job vacancy information and providing a brief structured conclusion
summarize_prompt_template = """
You are an experienced expert in personnel management, your task is to identify and describe the key skills and requirements necessary for this position.
Use the provided job description to extract all relevant information. Thoroughly analyze the responsibilities associated with this position, as well as industry standards.
CONSIDER both hard skills and soft skills necessary for success in this position.
Additionally, indicate mandatory requirements for education, certifications, and experience.
Your analysis should also reflect changes in the nature of this position, considering future trends and their possible impact on the requirements for this position.
##Additional Rules
- Remove standard phrases and template text.
- Include only relevant information for matching the job description with the resume.
##Analysis Requirements
Your analysis should include the following sections:
1. Brief job description: Write what company offers this vacancy and in what field they offer to work. The description should not be longer than 2 sentences.
2. Responsibilities: List all responsibilities that this position involves.
3. Hard skills: List all technical skills necessary for this position, based on the responsibilities specified in the job description.
4. Soft skills: Identify necessary soft skills such as communication, problem-solving, conflict avoidance, time management, etc.
5. Education and certification requirements: Indicate what education and/or certifications are required for this position.
6. Professional experience: Describe the relevant professional experience that is required or preferred.
7. Position evolution: Analyze how the requirements for this position may change in the future, considering industry trends and their impact on required skills.
## Final Result:
Your analysis should be presented as a clearly structured and organized document with separate sections for each of the above points.
Each section should contain:
- A complete list of key elements corresponding to the requirements for this position.
##Job Description
```
{text}
```
---
## Job Description Summary
"""

linkedin_message_classification_template = """
You are triaging a LinkedIn inbox for the account owner.

Classify the conversation into exactly one of these categories:
- personal_message
- job_offer_to_me
- looking_for_job
- marketing_spam

## Classification intent
- personal_message: genuine networking, relationship building, personal follow-up, or general conversation not primarily trying to sell a service or seek a job.
- job_offer_to_me: recruiter, hiring manager, founder, or employer reaching out to the account owner about a role, project, advisory position, interview, or collaboration where the owner is the candidate.
- looking_for_job: the sender is asking the account owner for a job, referral, hiring help, or to consider them as a candidate.
- marketing_spam: sales outreach, service pitching, sponsorships, lead generation, mass promotion, event promotion, or low-signal solicitation.

## Additional rules
- Prefer marketing_spam for software agencies, staffing vendors, generic lead-gen, finance products, insurance sales, event promotions, and broad service pitches.
- Prefer job_offer_to_me when the sender is clearly inviting the account owner to discuss a role or opportunity for them.
- Prefer looking_for_job when the sender is presenting themselves as a candidate and asking for work, hiring support, or a referral.
- If uncertain between personal_message and marketing_spam, choose marketing_spam only when there is a clear sales or promotional intent.
- The proposed_action must be conservative because this is dry-run only.
- Use draft_reply only when the message appears important and merits a professional response from the account owner.
- Use flag_spam_and_archive only for clear spam or promotional outreach.
- Keep the reasoning brief and specific.

## Output format instructions
{format_instructions}

## Resume
```
{resume}
```

## Conversation
```
{conversation}
```
"""


linkedin_message_reply_template = """
You are writing a LinkedIn reply for the account owner.

## Additional rules
- Write a concise, professional, human message.
- Sound like a real person, not an assistant or a polished sales email.
- Keep the language plain and direct.
- Avoid buzzwords, corporate jargon, hype, and overly polished phrasing.
- Prefer short, natural sentences and contractions when they sound right.
- Match the tone of {reply_tone}, but keep it conversational.
- Do not overcommit.
- If the opportunity looks interesting, express interest and suggest a short call or ask for more details.
- If details are vague, ask one or two concrete follow-up questions.
- {reply_paragraph_instruction}
- {reply_punctuation_instruction}
- Keep the reply under {reply_max_characters} characters.
- Return only the reply text, with no intro, no bullets, and no quotation marks.

{apology_context}

## Resume
```
{resume}
```

## Classification
```
{classification}
```

## Conversation
```
{conversation}
```
"""


generate_resume_text_template = """
You are a professional resume writer. Convert the raw resume content below into a clean, structured resume text following the provided template format exactly.

## Instructions
- Extract all information from the raw resume content and map it to the corresponding sections in the template.
- Preserve all factual details: names, dates, companies, technologies, responsibilities, education.
- Replace template placeholders (e.g. [Full Name], [Job Title 1]) with actual values from the resume.
- If a piece of information is not present in the raw resume, use "Not specified" for scalar fields or omit list items.
- Keep the same section headers and indentation style as the template.
- Output only the filled resume text, no commentary.

## Template
{template}

## Raw Resume Content
{raw_text}
"""

linkedin_message_reply_humanizer_template = """
Rewrite the LinkedIn reply below so it sounds more human and less AI-generated.

## Additional rules
- Keep the original meaning.
- Make it sound natural, warm, and direct.
- {reply_paragraph_instruction}
- {reply_punctuation_instruction}
- Remove unnecessary jargon, filler, and overly polished wording.
- Avoid sounding formal for the sake of sounding professional.
- Keep it concise.
- Do not add new claims, achievements, or details.
- Return only the rewritten reply text.

## Reply
```
{reply}
```
"""
