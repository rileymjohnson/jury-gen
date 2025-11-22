# Use the official AWS-provided Lambda base image for Python 3.12
FROM public.ecr.aws/lambda/python:3.12

# Copy the requirements file into the container
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

# Install the Python packages
RUN pip install -r ${LAMBDA_TASK_ROOT}/requirements.txt

# --- This is the key part ---
# Run the NLTK downloader to fetch the 'punkt' tokenizer
# This bakes the data right into the container image.
RUN python -m nltk.downloader punkt

# Copy the rest of your Lambda function's code
COPY main.py ${LAMBDA_TASK_ROOT}/

# Set the command (the entrypoint) to your handler
CMD [ "main.lambda_handler" ]