#include "nimbus.h"

#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusReply>

namespace Nimbus
{
QDBusMessage call(const QString &method, const QVariantList &args)
{
    QDBusMessage msg = QDBusMessage::createMethodCall(Service, Path, Interface, method);
    msg.setArguments(args);
    return msg;
}

QStringList roots(int timeoutMs)
{
    QDBusConnection bus = QDBusConnection::sessionBus();
    if (!bus.interface() || !bus.interface()->isServiceRegistered(Service)) {
        return {};
    }
    QDBusReply<QStringList> reply = bus.call(call(QStringLiteral("GetRoots")), QDBus::Block, timeoutMs);
    return reply.isValid() ? reply.value() : QStringList{};
}

bool isUnder(const QString &path, const QStringList &roots)
{
    for (const QString &root : roots) {
        if (path == root || path.startsWith(root + QLatin1Char('/'))) {
            return true;
        }
    }
    return false;
}

QString hinted(const QString &path, bool isDir)
{
    return isDir && !path.endsWith(QLatin1Char('/')) ? path + QLatin1Char('/') : path;
}

void notify(const QString &title, const QString &body)
{
    QDBusMessage msg = QDBusMessage::createMethodCall(QStringLiteral("org.freedesktop.Notifications"),
                                                      QStringLiteral("/org/freedesktop/Notifications"),
                                                      QStringLiteral("org.freedesktop.Notifications"),
                                                      QStringLiteral("Notify"));
    msg.setArguments({QStringLiteral("Nimbus Drive"), 0u, QStringLiteral("io.github.nimbusdrive"), title, body,
                      QStringList{}, QVariantMap{}, -1});
    QDBusConnection::sessionBus().call(msg, QDBus::NoBlock);
}
}
