# 빌드 스테이지
FROM node:18-alpine as build

WORKDIR /app

# 패키지 매니저 파일 복사 및 의존성 설치
COPY package*.json ./
RUN npm install

# 애플리케이션 코드 복사 및 빌드
COPY . .
RUN npm run build

# 프로덕션 스테이지 (nginx로 서빙)
FROM nginx:alpine

# 빌드된 파일을 nginx로 복사
COPY --from=build /app/dist /usr/share/nginx/html

# nginx 설정 (API 프록시 포함)
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]