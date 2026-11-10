FROM python:3.13-slim
WORKDIR /app
COPY app.py .
ENV PORT=5000
EXPOSE 5000
CMD ["python", "-u", "app.py"]
