"""Kafka consumer that reads and displays earthquake events."""

from __future__ import annotations

import click
from confluent_kafka import Consumer, KafkaError
from rich.console import Console
from rich.table import Table

from quake_stream.models import Earthquake

TOPIC = "earthquakes"
console = Console()


def run_consumer(
    bootstrap_servers: str = "localhost:9092",
    group_id: str = "quake-display",
) -> None:
    """Consume earthquake events from Kafka and display them."""
    conf = {
        "bootstrap.servers": bootstrap_servers,
        "group.id": group_id,
        "auto.offset.reset": "earliest",
    }
    consumer = Consumer(conf)
    consumer.subscribe([TOPIC])

    click.echo(f"Consumer started — listening on topic '{TOPIC}'")

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                click.echo(f"Consumer error: {msg.error()}", err=True)
                continue

            quake = Earthquake.from_json(msg.value().decode("utf-8"))
            _print_quake(quake)
    except KeyboardInterrupt:
        click.echo("\nShutting down consumer...")
    finally:
        consumer.close()


def _print_quake(q: Earthquake) -> None:
    color = "red" if q.magnitude >= 5.0 else "yellow" if q.magnitude >= 3.0 else "green"
    console.print(
        f"[bold {color}]M{q.magnitude:.1f}[/] {q.place} "
        f"(depth {q.depth:.1f} km) — {q.time:%Y-%m-%d %H:%M UTC}"
    )
