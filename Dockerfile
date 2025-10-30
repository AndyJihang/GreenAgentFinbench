FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 7001 7002
ENV AB_OUTPUT_DIR=/outputs
RUN mkdir -p /outputs
ENTRYPOINT ["bash","entrypoint.sh"]
