FROM public.ecr.aws/lambda/python:3.12

# Install dependencies
RUN pip install --no-cache-dir python-docx

# Copy function code
COPY main.py ${LAMBDA_TASK_ROOT}

# Handler
CMD ["main.lambda_handler"]

