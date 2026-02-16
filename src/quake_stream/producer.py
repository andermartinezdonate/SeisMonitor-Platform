"""Kafka producer that publishes earthquake events."""

from __future__ import annotations

import time

import click
from confluent_kafka import Producer

from quake_stream.usgs_client import fetch_earthquakes

TOPIC = "earthquakes"


def delivery_report(err, msg):
    if err is not None:
        click.echo(f"Delivery failed: {err}", err=True)
    else:
        click.echo(f"Delivered to {msg.topic()}[{msg.partition()}] @ {msg.offset()}")


def run_producer(
    bootstrap_servers: str = "localhost:9092",
    period: str = "hour",
    interval: int = 60,
    min_magnitude: float = 0.0,
) -> None:
    """Poll USGS and publish earthquake events to Kafka."""
    conf = {"bootstrap.servers": bootstrap_servers}
    producer = Producer(conf)
    seen: set[str] = set()

    click.echo(f"Producer started — polling USGS every {interval}s (period={period})")

    while True:
        try:
            quakes = fetch_earthquakes(period=period, min_magnitude=min_magnitude)
            new = [q for q in quakes if q.id not in seen]
            for q in new:
                producer.produce(
                    TOPIC,
                    key=q.id,
                    value=q.to_json(),
                    callback=delivery_report,
                )
                seen.add(q.id)
            producer.flush()
            if new:
                click.echo(f"Published {len(new)} new earthquake(s)")
        except Exception as exc:
            click.echo(f"Error polling USGS: {exc}", err=True)

        time.sleep(interval)
