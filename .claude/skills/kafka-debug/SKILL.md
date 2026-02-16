# Kafka Debug Skill

## When to use
When Kafka containers fail to start, producers/consumers can't connect, or topics are missing.

## Debug steps

1. **Check container status:**
   ```bash
   docker compose ps
   docker compose logs kafka
   ```

2. **Verify Kafka is listening:**
   ```bash
   docker exec quake-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
   ```

3. **Create topic manually if needed:**
   ```bash
   docker exec quake-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --topic earthquakes --partitions 1 --replication-factor 1
   ```

4. **Test produce/consume from CLI:**
   ```bash
   echo "test" | docker exec -i quake-kafka /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server localhost:9092 --topic earthquakes
   docker exec quake-kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic earthquakes --from-beginning --max-messages 1
   ```

5. **Common issues:**
   - Port 9092 already in use → `lsof -i :9092`
   - Container not healthy → increase `start_period` in healthcheck
   - CLUSTER_ID mismatch → `docker compose down -v && docker compose up -d`
