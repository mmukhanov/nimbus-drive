// Right-click menu in Dolphin for files in the Google Drive folders.

#include "nimbus.h"

#include <KAbstractFileItemActionPlugin>
#include <KFileItem>
#include <KFileItemListProperties>
#include <KPluginFactory>

#include <QAction>
#include <algorithm>
#include <QDBusConnection>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QDBusReply>
#include <QIcon>
#include <QMenu>
#include <QMessageBox>
#include <QPointer>

class NimbusActions : public KAbstractFileItemActionPlugin
{
    Q_OBJECT
public:
    NimbusActions(QObject *parent, const QVariantList &)
        : KAbstractFileItemActionPlugin(parent)
    {
    }

    QList<QAction *> actions(const KFileItemListProperties &props, QWidget *parentWidget) override
    {
        const QStringList roots = Nimbus::roots();
        if (roots.size() < 2) {
            return {};
        }
        const QString mount = roots[0];
        QStringList paths, hinted;
        bool allDirs = true, anyInMount = false;
        for (const KFileItem &item : props.items()) {
            const QString p = item.localPath();
            if (p.isEmpty() || !Nimbus::isUnder(p, roots) || roots.contains(p)) {
                return {};
            }
            paths << p;
            hinted << Nimbus::hinted(p, item.isDir());
            allDirs = allDirs && item.isDir();
            anyInMount = anyInMount || Nimbus::isUnder(p, {mount});
        }
        if (paths.isEmpty()) {
            return {};
        }

        QDBusReply<QStringList> reply = QDBusConnection::sessionBus().call(
            Nimbus::call(QStringLiteral("GetStatuses"), {hinted}), QDBus::Block, 500);
        const QStringList states = reply.isValid() ? reply.value() : QStringList{};
        const bool allOffline = !states.isEmpty() && std::all_of(states.begin(), states.end(), [](const QString &s) {
            return s == QLatin1String("offline") || s == QLatin1String("syncing") || s == QLatin1String("pending")
                || s == QLatin1String("conflict") || s == QLatin1String("error");
        });

        auto *menu = new QMenu(parentWidget);
        auto *menuAction = new QAction(QIcon::fromTheme(QStringLiteral("io.github.nimbusdrive")),
                                       QStringLiteral("Google Drive"), parentWidget);
        menuAction->setMenu(menu);

        if (anyInMount) {
            add(menu, QStringLiteral("nimbusdrive-cached"), QStringLiteral("Download to this computer"), [paths] {
                callAndReport(QStringLiteral("Download"), {paths}, false);
            });
            add(menu, QStringLiteral("nimbusdrive-cloud"), QStringLiteral("Free up space (online only)"), [paths] {
                callAndReport(QStringLiteral("FreeSpace"), {paths}, true);
            });
        }
        if (allDirs) {
            QAction *offline = add(menu, QStringLiteral("nimbusdrive-offline"), QStringLiteral("Always keep offline"),
                                   [paths, allOffline, parentWidget = QPointer<QWidget>(parentWidget)] {
                                       if (!allOffline) {
                                           callAndReport(QStringLiteral("SetOffline"), {paths, true, false}, true);
                                           return;
                                       }
                                       const auto answer = QMessageBox::question(
                                           parentWidget, QStringLiteral("Stop keeping offline"),
                                           QStringLiteral("The folder stays in the cloud. "
                                                          "Move its local offline copy to the Trash?"),
                                           QMessageBox::Yes | QMessageBox::No | QMessageBox::Cancel, QMessageBox::No);
                                       if (answer == QMessageBox::Cancel) {
                                           return;
                                       }
                                       callAndReport(QStringLiteral("SetOffline"),
                                                     {paths, false, answer == QMessageBox::Yes}, true);
                                   });
            offline->setCheckable(true);
            offline->setChecked(allOffline);
        }
        if (allOffline) {
            add(menu, QStringLiteral("nimbusdrive-syncing"), QStringLiteral("Sync now"), [] {
                QDBusConnection::sessionBus().call(Nimbus::call(QStringLiteral("SyncNow")), QDBus::NoBlock);
            });
        }
        return {menuAction};
    }

private:
    template<typename F>
    static QAction *add(QMenu *menu, const QString &icon, const QString &text, F &&slot)
    {
        QAction *a = menu->addAction(QIcon::fromTheme(icon), text);
        QObject::connect(a, &QAction::triggered, a, std::forward<F>(slot));
        return a;
    }

    // Long operations run in the daemon; the menu returns at once and reports when done.
    static void callAndReport(const QString &method, const QVariantList &args, bool showResult)
    {
        auto *w = new QDBusPendingCallWatcher(
            QDBusConnection::sessionBus().asyncCall(Nimbus::call(method, args), 120000));
        QObject::connect(w, &QDBusPendingCallWatcher::finished, [showResult](QDBusPendingCallWatcher *w) {
            w->deleteLater();
            QDBusPendingReply<QString> reply = *w;
            if (reply.isError()) {
                Nimbus::notify(QStringLiteral("Google Drive"), reply.error().message());
            } else if (showResult && !reply.value().isEmpty()) {
                Nimbus::notify(QStringLiteral("Google Drive"), reply.value());
            }
        });
    }
};

K_PLUGIN_CLASS_WITH_JSON(NimbusActions, "nimbusactions.json")

#include "actionplugin.moc"
