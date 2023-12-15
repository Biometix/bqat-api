echo "starting test server..."
docker compose -f docker-compose.dev.yml up -d
echo "waiting for server initialization..."
sleep 10; until curl 0.0.0.0:8848/scan/info; do printf waiting... && sleep 5; done
printf "\nrunning tests...\n"
docker compose exec -it server python3 -m pytest tests -v
echo "cleaning up..."
docker compose down
echo "finished."
