FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지 설치
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    socat \
    && rm -rf /var/lib/apt/lists/*

# AWS CLI 설치
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" \
    && unzip awscliv2.zip \
    && ./aws/install \
    && rm -rf aws awscliv2.zip

# Session Manager Plugin 설치
RUN curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o "session-manager-plugin.deb" \
    && dpkg -i session-manager-plugin.deb \
    && rm session-manager-plugin.deb

# AWS CLI 캐시 디렉토리 생성 및 권한 설정
RUN mkdir -p /tmp/aws-cli-cache \
    && chmod 777 /tmp/aws-cli-cache

# AWS CLI 환경 변수 설정
ENV AWS_CLI_FILE_ENCODING=UTF-8
ENV AWS_DEFAULT_OUTPUT=json
ENV AWS_CLI_CACHE_DIR=/tmp/aws-cli-cache

# Python 의존성 설치
COPY ./web-version/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY ./web-version/backend/ /app/

# AWS 설정 파일 복사
RUN mkdir -p /root/.aws
COPY ./web-version/backend/config /root/.aws/config
COPY ./web-version/backend/credentials /root/.aws/credentials
RUN chmod 600 /root/.aws/config /root/.aws/credentials

# 원본 스크립트 복사 (기존 코드 재활용)
COPY ./ec2menu_v5.1.9.py /app/ec2menu_v5_1_9.py

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]