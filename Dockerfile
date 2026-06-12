# LedgerBench: offline demo works out of the box; no keys baked, ever.
FROM python:3.12-slim

RUN useradd --create-home ledgerbench
WORKDIR /home/ledgerbench/app

# The wheel is built by CI (release.yml) into dist/ before docker build.
COPY dist/*.whl /tmp/dist/
RUN pip install --no-cache-dir /tmp/dist/*.whl && rm -rf /tmp/dist

# The demo needs the bundled worlds and the item bank (data, not code).
COPY benchmark/worlds/ benchmark/worlds/
COPY benchmark/items/public_v1.jsonl benchmark/items/public_v1.jsonl

RUN chown -R ledgerbench:ledgerbench /home/ledgerbench
USER ledgerbench

ENTRYPOINT ["ledgerbench"]
CMD ["demo", "--no-open"]
