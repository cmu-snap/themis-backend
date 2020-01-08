require('dotenv').config();
module.exports = {
  "development": {
    "url": `postgres://${process.env.DB_USERNAME}:${process.env.DB_PASSWORD}@postgres:${process.env.DB_PORT}/${process.env.DB_DATABASE}`,
    "dialect": "postgres"
  }
};
