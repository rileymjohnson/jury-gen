# Use the official AWS-provided Lambda base image for Python 3.12
FROM public.ecr.aws/lambda/python:3.12

# Copy the requirements file into the container
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

# Install the Python packages
RUN pip install -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy your Lambda function code (all needed modules)
COPY main.py ${LAMBDA_TASK_ROOT}/
COPY instruction_processing.py ${LAMBDA_TASK_ROOT}/

# Set the command (the entrypoint) to your handler
CMD [ "main.lambda_handler" ]
