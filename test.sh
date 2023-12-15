echo "starting test server..."
docker compose up -d
echo "waiting for server initialization..."
sleep 5; until curl 0.0.0.0:8848/scan/info; do echo waiting && sleep 5; done
echo "running tests..."
docker compose exec -it server python3 -m pytest tests -v
echo "cleaning up..."
docker compose down
echo "finished."
