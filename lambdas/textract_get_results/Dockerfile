# Use the official AWS-provided Lambda base image for Python 3.12
FROM public.ecr.aws/lambda/python:3.12

# Copy the requirements file into the container
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

# Install the Python packages
RUN pip install -r ${LAMBDA_TASK_ROOT}/requirements.txt

# --- Bundle NLTK tokenizers ---
# Download 'punkt' and (if available) 'punkt_tab' into the function code dir
# and point NLTK to it via NLTK_DATA. This avoids runtime downloads.
ENV NLTK_DATA=${LAMBDA_TASK_ROOT}/nltk_data
RUN mkdir -p ${NLTK_DATA} \
 && python -m nltk.downloader -d ${NLTK_DATA} punkt \
 && (python -m nltk.downloader -d ${NLTK_DATA} punkt_tab || true)

# Copy the rest of your Lambda function's code
COPY main.py ${LAMBDA_TASK_ROOT}/

# Set the command (the entrypoint) to your handler
CMD [ "main.lambda_handler" ]
