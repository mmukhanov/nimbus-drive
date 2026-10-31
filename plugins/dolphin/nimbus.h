// Shared bits of the Dolphin plugins: talking to the Nimbus Drive daemon over D-Bus.
#pragma once

#include <QDBusMessage>
#include <QString>
#include <QStringList>

namespace Nimbus
{
inline const QString Service = QStringLiteral("io.github.nimbusdrive");
inline const QString Path = QStringLiteral("/io/github/nimbusdrive");
inline const QString Interface = QStringLiteral("io.github.nimbusdrive.Daemon");

QDBusMessage call(const QString &method, const QVariantList &args = {});

// Mount point and offline-copy root, or empty if the daemon is not running.
QStringList roots(int timeoutMs = 300);

bool isUnder(const QString &path, const QStringList &roots);

// Path as sent to the daemon: directories carry a trailing slash.
QString hinted(const QString &path, bool isDir);

void notify(const QString &title, const QString &body);
}
