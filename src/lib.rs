mod event_loop;
mod events;
mod types;
mod window;

use pyo3::prelude::*;

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Event loop
    m.add_class::<event_loop::TaoEventLoop>()?;
    m.add_class::<event_loop::TaoEventLoopProxy>()?;

    // Window
    m.add_class::<window::TaoWindowBuilder>()?;
    m.add_class::<window::TaoWindow>()?;

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

    // Events
    m.add_class::<events::TaoEvent>()?;
    m.add_class::<events::ResizedEvent>()?;
    m.add_class::<events::MovedEvent>()?;
    m.add_class::<events::CloseRequestedEvent>()?;
    m.add_class::<events::DestroyedEvent>()?;
    m.add_class::<events::FocusedEvent>()?;
    m.add_class::<events::UnfocusedEvent>()?;
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

    Ok(())
}
