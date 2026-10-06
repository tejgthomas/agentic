import MapKit
import Observation

struct Location: Decodable {
    var lat: CLLocationDegrees
    var lon: CLLocationDegrees
}

@Observable
final class LocManagerViewModel {
    static let shared = LocManagerViewModel()
    private init() {}

    private(set) var location = Location(lat: 0.0, lon: 0.0)

    func setLocation(lat: CLLocationDegrees, lon: CLLocationDegrees) {
        location.lat = lat
        location.lon = lon
    }
}

final class LocManager: NSObject, CLLocationManagerDelegate {
    static let shared = LocManager()
    private let locManager = CLLocationManager()

    override private init() {
        super.init()
        locManager.desiredAccuracy = kCLLocationAccuracyBest
        locManager.delegate = self
    }

    func startUpdates() {
        if locManager.authorizationStatus == .notDetermined {
            locManager.requestWhenInUseAuthorization()
        }

        Task {
            do {
                for try await update in CLLocationUpdate.liveUpdates() {
                    if let loc = update.location {
                        LocManagerViewModel.shared.setLocation(
                            lat: loc.coordinate.latitude,
                            lon: loc.coordinate.longitude)
                    }
                }
            } catch {
                print(error.localizedDescription)
            }
        }
    }
}
