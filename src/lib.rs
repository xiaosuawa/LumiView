mod event_loop;
mod events;
mod menu;
mod monitor;
mod tray;
mod types;
mod window;

use pyo3::prelude::*;

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Event loop
    m.add_class::<event_loop::TaoEventLoop>()?;
    m.add_class::<event_loop::TaoEventLoopProxy>()?;

    // Window
    m.add_class::<window::TaoWindow>()?;

    // Monitors
    m.add_class::<monitor::Monitor>()?;
    m.add_class::<monitor::VideoMode>()?;

    // Types
    m.add_class::<types::WindowHandleKind>()?;
    m.add_class::<types::EventLoopControl>()?;
    m.add_class::<types::EventKind>()?;
    m.add_class::<types::ModifiersState>()?;
    m.add_class::<types::MouseButton>()?;
    m.add_class::<types::ElementState>()?;
    m.add_class::<types::ScrollDeltaKind>()?;
    m.add_class::<types::TouchPhase>()?;
    m.add_class::<types::KeyLocation>()?;
    m.add_class::<types::Theme>()?;
    m.add_class::<types::WindowEffect>()?;
    m.add_class::<types::ResizeDirection>()?;
    m.add_class::<types::CursorIcon>()?;
    m.add_class::<types::AttentionType>()?;
    m.add_class::<types::StartCause>()?;
    m.add_class::<types::ProgressState>()?;
    m.add_class::<types::VibrancyMaterial>()?;
    m.add_class::<types::ActivationPolicy>()?;

    // Menus (muda)
    m.add_class::<menu::TaoMenu>()?;
    m.add_class::<menu::TaoMenuItem>()?;
    m.add_class::<menu::TaoSubmenu>()?;
    m.add_class::<menu::TaoCheckMenuItem>()?;
    m.add_class::<menu::TaoPredefinedMenuItem>()?;
    m.add_class::<menu::MenuItemActivatedEvent>()?;

    // Tray (tray-icon)
    m.add_class::<tray::TaoTrayIcon>()?;
    m.add_class::<tray::TrayIconClickEvent>()?;
    m.add_class::<tray::TrayIconDoubleClickEvent>()?;
    m.add_class::<tray::TrayIconEnterEvent>()?;
    m.add_class::<tray::TrayIconMoveEvent>()?;
    m.add_class::<tray::TrayIconLeaveEvent>()?;

    // Events
    m.add_class::<events::TaoEvent>()?;
    m.add_class::<events::ResizedEvent>()?;
    m.add_class::<events::MovedEvent>()?;
    m.add_class::<events::CloseRequestedEvent>()?;
    m.add_class::<events::DestroyedEvent>()?;
    m.add_class::<events::FocusedEvent>()?;
    m.add_class::<events::UnfocusedEvent>()?;
    m.add_class::<events::ReopenEvent>()?;
    m.add_class::<events::ScaleFactorChangedEvent>()?;
    m.add_class::<events::ThemeChangedEvent>()?;
    m.add_class::<events::MouseInputEvent>()?;
    m.add_class::<events::CursorMovedEvent>()?;
    m.add_class::<events::MouseWheelEvent>()?;
    m.add_class::<events::KeyboardInputEvent>()?;
    m.add_class::<events::ModifiersChangedEvent>()?;
    m.add_class::<events::CursorEnteredEvent>()?;
    m.add_class::<events::CursorLeftEvent>()?;
    m.add_class::<events::RedrawRequestedEvent>()?;
    m.add_class::<events::UserEvent>()?;
    m.add_class::<events::LoopDestroyedEvent>()?;
    // Window lifecycle
    m.add_class::<events::StartedEvent>()?;
    m.add_class::<events::SuspendedEvent>()?;
    m.add_class::<events::ResumedEvent>()?;
    m.add_class::<events::StoppedEvent>()?;
    m.add_class::<events::DecorationsClickEvent>()?;
    m.add_class::<events::ReceivedImeTextEvent>()?;
    m.add_class::<events::TouchpadPressureEvent>()?;
    m.add_class::<events::AxisMotionEvent>()?;
    m.add_class::<events::TouchEvent>()?;
    // Loop-level events
    m.add_class::<events::NewEventsEvent>()?;
    m.add_class::<events::MainEventsClearedEvent>()?;
    m.add_class::<events::RedrawEventsClearedEvent>()?;
    m.add_class::<events::OpenedEvent>()?;
    // Device events
    m.add_class::<events::DeviceAddedEvent>()?;
    m.add_class::<events::DeviceRemovedEvent>()?;
    m.add_class::<events::DeviceMouseMotionEvent>()?;
    m.add_class::<events::DeviceMouseWheelEvent>()?;
    m.add_class::<events::DeviceMotionEvent>()?;
    m.add_class::<events::DeviceButtonEvent>()?;
    m.add_class::<events::DeviceKeyEvent>()?;
    m.add_class::<events::DeviceTextEvent>()?;

    // Functions
    m.add_function(wrap_pyfunction!(events::parse_key_code, m)?)?;
    m.add_function(wrap_pyfunction!(event_loop::set_loop_running, m)?)?;
    m.add_function(wrap_pyfunction!(menu::init_menu_events, m)?)?;
    m.add_function(wrap_pyfunction!(tray::init_tray_events, m)?)?;

    Ok(())
}
