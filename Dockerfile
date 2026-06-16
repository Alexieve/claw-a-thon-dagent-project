# Stage 1: Build the React UI
FROM oven/bun:1-alpine AS ui-builder
WORKDIR /ui
COPY ui/package.json ui/bun.lock ./
RUN bun install --frozen-lockfile
COPY ui/ .
RUN bun run build

# Stage 2: Python agent runtime
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=ui-builder /ui/dist ./ui/dist
EXPOSE 8080
CMD ["python", "main.py"]
