FROM node:13
WORKDIR /app
COPY ./package.json .
COPY ./package-lock.json .

RUN npm install

COPY . .

EXPOSE 9000 8000

CMD npm start