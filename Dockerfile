FROM python:3.8-alpine as base

# Docker multistage build to obtain
# a minimal image
# -------------------
FROM base as builder

RUN mkdir /install
WORKDIR /install

COPY requirements.txt /

RUN pip install \
        --prefix=/install \
        -r /requirements.txt

# -------------------
# final minimal image
FROM base

# get the built pip requirements from
# the previous stage
COPY --from=builder /install /usr/local

# copy the script
COPY ./controller.py /

# show the help file
CMD python ./controller.py --help