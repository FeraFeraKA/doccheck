FROM nginx:1.31.8-alpine AS download
ADD --checksum=sha256:f3f180f1d93aa72cce4e6386f98cc06569a0146fbd65eb4423cf83e6434bcfe6 \
    https://github.com/jpillora/chisel/releases/download/v1.12.0/chisel_1.12.0_linux_amd64.gz \
    /tmp/chisel.gz
RUN gzip -dc /tmp/chisel.gz > /usr/local/bin/chisel && chmod 0755 /usr/local/bin/chisel

FROM nginx:1.31.8-alpine
COPY --from=download /usr/local/bin/chisel /usr/local/bin/chisel
COPY nginx.conf.template start.sh /opt/doccheck/
USER nginx
ENTRYPOINT ["/bin/sh", "/opt/doccheck/start.sh"]
