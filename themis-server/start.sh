#!/bin/bash
npm run migrate
docker run --name themis-cache -p 6379:6379 --restart always --detach redis
npm run start:dev