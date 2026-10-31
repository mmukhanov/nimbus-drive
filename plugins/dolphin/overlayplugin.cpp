// Emblems on files in the Google Drive folders, like Google Drive for Windows shows them.
//
// Dolphin asks for overlays item by item on its GUI thread, so nothing here blocks:
// unknown items are queued, asked for in one batched D-Bus call, and their emblems
// arrive later through overlaysChanged(). The daemon pushes StatusChanged signals
// when a file starts or finishes downloading, uploading or syncing.

#include "nimbus.h"

#include <KOverlayIconPlugin>

#include <QDBusConnection>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QDBusServiceWatcher>
#include <QFileInfo>
#include <QHash>
#include <QSet>
#include <QTimer>
#include <QUrl>

// Dolphin loads overlay plugins with a bare QPluginLoader and casts the instance to
// KOverlayIconPlugin, so the class itself is the plugin root (no KPluginFactory).
class NimbusOverlay : public KOverlayIconPlugin
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID "io.github.nimbusdrive.overlayicon" FILE "nimbusoverlay.json")
public:
    explicit NimbusOverlay(QObject *parent = nullptr)
        : KOverlayIconPlugin(parent)
    {
        m_batch.setSingleShot(true);
        m_batch.setInterval(30);
        connect(&m_batch, &QTimer::timeout, this, &NimbusOverlay::sendBatch);

        QDBusConnection bus = QDBusConnection::sessionBus();
        bus.connect(Nimbus::Service, Nimbus::Path, Nimbus::Interface, QStringLiteral("StatusChanged"), this,
                    SLOT(onStatusChanged(QStringList)));
        auto *watcher = new QDBusServiceWatcher(Nimbus::Service, bus,
                                                QDBusServiceWatcher::WatchForOwnerChange, this);
        connect(watcher, &QDBusServiceWatcher::serviceRegistered, this, &NimbusOverlay::fetchRoots);
        connect(watcher, &QDBusServiceWatcher::serviceUnregistered, this, &NimbusOverlay::daemonGone);
        fetchRoots();
    }

    QStringList getOverlays(const QUrl &url) override
    {
        if (!url.isLocalFile()) {
            return {};
        }
        const QString path = url.toLocalFile();
        if (m_rootsKnown ? !Nimbus::isUnder(path, m_roots) : m_urls.size() > 5000) {
            return {}; // not ours, or the daemon is not running and we would only hoard URLs
        }
        m_urls.insert(path, url);
        const auto it = m_state.constFind(path);
        if (it != m_state.constEnd()) {
            return emblems(it.value());
        }
        enqueue(path);
        return {};
    }

private Q_SLOTS:
    void onStatusChanged(const QStringList &paths)
    {
        for (const QString &p : paths) {
            if (p.endsWith(QLatin1Char('/'))) {
                for (auto it = m_urls.constBegin(); it != m_urls.constEnd(); ++it) {
                    if (it.key().startsWith(p)) {
                        enqueue(it.key());
                    }
                }
            } else if (m_urls.contains(p)) {
                enqueue(p);
            }
        }
    }

private:
    static QStringList emblems(const QString &state)
    {
        return state.isEmpty() ? QStringList{} : QStringList{QStringLiteral("nimbusdrive-") + state};
    }

    void enqueue(const QString &path)
    {
        m_queue.insert(path);
        if (m_rootsKnown && !m_batch.isActive()) {
            m_batch.start();
        }
    }

    void fetchRoots()
    {
        auto *w = new QDBusPendingCallWatcher(
            QDBusConnection::sessionBus().asyncCall(Nimbus::call(QStringLiteral("GetRoots")), 5000), this);
        connect(w, &QDBusPendingCallWatcher::finished, this, [this](QDBusPendingCallWatcher *w) {
            w->deleteLater();
            QDBusPendingReply<QStringList> reply = *w;
            if (reply.isError()) {
                return; // daemon not running; the service watcher retries when it appears
            }
            m_roots = reply.value();
            m_rootsKnown = true;
            m_state.clear();
            for (auto it = m_urls.constBegin(); it != m_urls.constEnd(); ++it) {
                if (Nimbus::isUnder(it.key(), m_roots)) {
                    m_queue.insert(it.key());
                }
            }
            sendBatch();
        });
    }

    void daemonGone()
    {
        const auto known = m_state;
        m_state.clear();
        for (auto it = known.constBegin(); it != known.constEnd(); ++it) {
            if (!it.value().isEmpty()) {
                Q_EMIT overlaysChanged(m_urls.value(it.key()), {});
            }
        }
    }

    void sendBatch()
    {
        if (m_queue.isEmpty()) {
            return;
        }
        QStringList paths, hinted;
        for (const QString &p : std::as_const(m_queue)) {
            if (!Nimbus::isUnder(p, m_roots)) {
                continue;
            }
            paths << p;
            // Dolphin has just listed this item, so the stat is answered from cache.
            hinted << Nimbus::hinted(p, QFileInfo(p).isDir());
        }
        m_queue.clear();
        if (paths.isEmpty()) {
            return;
        }
        auto *w = new QDBusPendingCallWatcher(
            QDBusConnection::sessionBus().asyncCall(Nimbus::call(QStringLiteral("GetStatuses"), {hinted}), 10000),
            this);
        connect(w, &QDBusPendingCallWatcher::finished, this, [this, paths](QDBusPendingCallWatcher *w) {
            w->deleteLater();
            QDBusPendingReply<QStringList> reply = *w;
            if (reply.isError()) {
                return;
            }
            const QStringList states = reply.value();
            for (int i = 0; i < paths.size() && i < states.size(); ++i) {
                const QString &p = paths[i];
                const auto old = m_state.constFind(p);
                if (old != m_state.constEnd() && old.value() == states[i]) {
                    continue;
                }
                m_state.insert(p, states[i]);
                Q_EMIT overlaysChanged(m_urls.value(p, QUrl::fromLocalFile(p)), emblems(states[i]));
            }
        });
    }

    QStringList m_roots;
    bool m_rootsKnown = false;
    QHash<QString, QString> m_state; // local path -> daemon state
    QHash<QString, QUrl> m_urls;     // local path -> URL as Dolphin passed it
    QSet<QString> m_queue;
    QTimer m_batch;
};

#include "overlayplugin.moc"
