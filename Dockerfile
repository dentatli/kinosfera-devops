FROM alpine:3.22
RUN apk add --no-cache curl tini logrotate \
    && addgroup -g 10001 bingo \
    && adduser -D -H -u 10001 -G bingo bingo \
    && mkdir -p /opt/bingo/logs /opt/bongo/logs \
    && chown -R bingo:bingo /opt/bingo /opt/bongo
COPY --chmod=755 bingo /usr/local/bin/bingo
COPY --chmod=755 scripts/app-entrypoint.sh /usr/local/bin/app-entrypoint
COPY config/bingo-logrotate.conf /etc/logrotate.d/bingo
USER 10001:10001
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/app-entrypoint"]
CMD ["run_server"]
