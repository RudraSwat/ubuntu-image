ARG UBUNTU_RELEASE=rolling

FROM ubuntu:$UBUNTU_RELEASE

ARG DESKTOP=nogui

RUN userdel -r ubuntu || :

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -yq python3 \
                                                       python3-click \
                                                       python3-requests \
                                                       python3-fasteners \
                                                       umoci \
                                                       skopeo \
                                                       jq \
                                                       git \
                                                       sudo \
                                                       pacman-package-manager \
                                                       linux-generic \
                                                       systemd \
                                                       systemd-container \
                                                       locales \
                                                       grub2-common \
                                                       ubuntu-standard \
                                                       dracut

RUN if [ "$DESKTOP" = gnome ]; then apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -yq ubuntu-desktop; \
  elif [ "$DESKTOP" = plasma ]; then apt-get update; DEBIAN_FRONTEND=noninteractive apt-get install -yq kubuntu-desktop; fi
