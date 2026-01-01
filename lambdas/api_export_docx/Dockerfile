FROM public.ecr.aws/lambda/python:3.12

# Install dependencies via requirements.txt
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy function code
COPY main.py ${LAMBDA_TASK_ROOT}

# Handler
CMD ["main.lambda_handler"]
